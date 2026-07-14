from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile

from travel_agent.agent.travel_graph import unified_graph
from travel_agent.core.logging import get_logger
from travel_agent.memory.redis_memory import RedisMemoryStore
from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.intent_service import classify_chat_intent
from travel_agent.services.llm_chat_service import build_general_response
from travel_agent.services.request_builder import build_travel_request
from travel_agent.services.upload_service import extract_upload_context, merge_question_with_file_context

router = APIRouter(prefix='/chat', tags=['chat'])
memory_store = RedisMemoryStore()
logger = get_logger(__name__)


def _new_conversation_id() -> str:
    return str(uuid4())


def _friendly_error_response(request: ChatRequest, message: str, code: str) -> dict[str, Any]:
    response = build_general_response(request)
    response['final_answer'] = message
    response['error'] = code
    return response


def _ensure_response_fields(response: dict[str, Any], request: ChatRequest, upload_context: dict | None = None) -> dict[str, Any]:
    response.setdefault('conversation_id', request.conversation_id or _new_conversation_id())
    response.setdefault('answer_type', 'general_chat')
    response.setdefault('final_answer', '')
    response.setdefault('data', {})
    response.setdefault('travel_request', None)
    response.setdefault('upload_context', upload_context)
    if not isinstance(response.get('meta'), dict):
        response['meta'] = {}
    response['meta']['memory'] = memory_store.status()
    response.setdefault('error', None)
    if upload_context and response.get('upload_context') is None:
        response['upload_context'] = upload_context
    if response.get('answer_type') == 'travel_planning' and response.get('travel_request') is None:
        response['travel_request'] = build_travel_request(request).model_dump()
    return response


async def _run_graph(request: ChatRequest, upload_context: dict | None = None) -> dict[str, Any]:
    try:
        graph_result = await asyncio.wait_for(
            unified_graph.ainvoke({'request': request, 'upload_context': upload_context, 'memory_store': memory_store}),
            timeout=45,
        )
        response = graph_result.get('response') or build_general_response(request)
        return _ensure_response_fields(response, request, upload_context)
    except asyncio.TimeoutError:
        logger.exception('Agent graph timed out')
        return _friendly_error_response(request, '请求处理超时，请稍后重试或检查地图/模型配置。', 'graph_timeout')
    except Exception:
        logger.exception('Agent graph failed')
        return _friendly_error_response(request, '请求处理失败，请稍后重试。', 'graph_failed')


def _remember(conversation_id: str, user_question: str, response: dict[str, Any], intent: str, upload_context: dict | None) -> None:
    final_answer = str(response.get('final_answer') or '')
    memory_store.append_turn(conversation_id, user_question, final_answer)
    memory_store.update_profile(conversation_id, {'last_question': user_question, 'intent': intent, 'last_upload': upload_context})
    if hasattr(memory_store, 'update_conversation_meta'):
        memory_store.update_conversation_meta(conversation_id, intent=intent)


@router.post('')
async def chat(request: ChatRequest) -> dict[str, Any]:
    conversation_id = request.conversation_id or _new_conversation_id()
    request = ChatRequest(**{**request.model_dump(), 'conversation_id': conversation_id})
    memory_store.get_context(conversation_id)
    intent = classify_chat_intent(request.question)
    response = _ensure_response_fields(await _run_graph(request), request)
    _remember(conversation_id, request.question, response, intent, None)
    return response


@router.get('')
def chat_health() -> dict[str, str]:
    return {'status': 'ok'}


@router.get('/conversations')
def list_conversations(limit: int = 20) -> dict[str, Any]:
    return {
        'conversations': memory_store.list_conversations(limit=limit),
        'meta': {'memory': memory_store.status()},
    }


@router.get('/history/{conversation_id}')
def get_conversation_history(conversation_id: str, limit: int = 10) -> dict[str, Any]:
    return {
        'conversation_id': conversation_id,
        'history': memory_store.get_history(conversation_id, limit=limit),
        'meta': {'memory': memory_store.status()},
    }


@router.post('/multimodal')
async def multimodal_chat(
    question: str = Form(...),
    conversation_id: str | None = Form(None),
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    origin: str | None = Form(None),
    destination: str | None = Form(None),
    preferences: str | None = Form(None),
    travel_mode: str | None = Form(None),
    waypoint_order: str | None = Form(None),
    waypoints_json: str | None = Form(None),
) -> dict[str, Any]:
    conversation_id = conversation_id or _new_conversation_id()
    memory_store.get_context(conversation_id)
    upload_context = None
    merged_question = question
    upload_file = audio or image
    base_payload = {
        'conversation_id': conversation_id,
        'image_context': None,
        'origin': origin,
        'destination': destination,
        'preferences': preferences,
        'travel_mode': travel_mode,
        'waypoint_order': str(waypoint_order).lower() == 'true' if waypoint_order is not None else None,
        'waypoints_json': waypoints_json,
        'force_current_anchor': True,
    }
    if upload_file is not None:
        try:
            content = await upload_file.read()
            upload_context = await asyncio.to_thread(extract_upload_context, upload_file, content)
        except Exception:
            logger.exception('Upload parsing failed')
            request_payload = ChatRequest(question=question, **base_payload)
            response = _friendly_error_response(request_payload, '文件解析失败，请换一个文件或重试。', 'upload_parse_failed')
            _remember(conversation_id, question, response, 'general_chat', upload_context)
            return _ensure_response_fields(response, request_payload, upload_context)
        if upload_context and upload_context.get('file_kind') == 'audio' and not str(upload_context.get('extracted_text') or '').strip():
            request_payload = ChatRequest(question=question, **base_payload)
            response = _friendly_error_response(request_payload, str(upload_context.get('extraction_error') or '语音识别失败'), 'audio_transcribe_failed')
            response['upload_context'] = upload_context
            _remember(conversation_id, question, response, 'general_chat', upload_context)
            return response
        transcript = str((upload_context or {}).get('extracted_text') or '').strip()
        if upload_context and upload_context.get('file_kind') == 'audio' and transcript:
            merged_question = transcript
        else:
            merged_question = merge_question_with_file_context(question, upload_context)
    request_payload = ChatRequest(question=merged_question, **base_payload)
    intent = classify_chat_intent(merged_question)
    response = _ensure_response_fields(await _run_graph(request_payload, upload_context), request_payload, upload_context)
    if upload_context and not str(response.get('final_answer') or '').strip():
        if upload_context.get('file_kind') == 'image':
            response['final_answer'] = f'已接收图片 {upload_context["filename"]}；当前版本暂未解析图片内容，可补充文字需求。'
        else:
            response['final_answer'] = f'已接收{upload_context.get("file_kind", "文件")} {upload_context["filename"]}'
    _remember(conversation_id, question, response, intent, upload_context)
    return _ensure_response_fields(response, request_payload, upload_context)
