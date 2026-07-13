from __future__ import annotations

import httpx

from travel_agent.core.config import get_settings
from travel_agent.core.logging import get_logger
from travel_agent.memory.redis_memory import RedisMemoryStore
from travel_agent.schemas.chat import ChatRequest

settings = get_settings()
logger = get_logger(__name__)


def build_general_response(request: ChatRequest) -> dict:
    return {
        'conversation_id': request.conversation_id or 'default',
        'answer_type': 'general_chat',
        'final_answer': '',
        'data': {},
        'travel_request': None,
        'upload_context': None,
        'meta': {'source': 'llm_general_chat'},
        'error': None,
    }


async def generate_general_answer(question: str, conversation_id: str, memory_store: RedisMemoryStore | None = None) -> str:
    if not settings.qwen_api_key:
        return '模型服务未配置，无法完成普通问答。'
    context = memory_store.get_context(conversation_id) if memory_store else {}
    short_term = context.get('short_term', []) if isinstance(context, dict) else []
    history_lines: list[str] = []
    for turn in short_term[-6:]:
        if not isinstance(turn, dict):
            continue
        user_text = str(turn.get('user_input') or turn.get('user') or '').strip()
        assistant_text = str(turn.get('assistant_output') or turn.get('assistant') or '').strip()
        if user_text:
            history_lines.append(f'用户：{user_text}')
        if assistant_text:
            history_lines.append(f'助手：{assistant_text}')
    history_text = '\n'.join(history_lines) if history_lines else '无'
    payload = {
        'model': settings.qwen_model,
        'messages': [
            {'role': 'system', 'content': '你是一个中文旅行与生活助理。旅行相关问题给出可执行建议；非旅行问题也要直接、简洁、自然回答。'},
            {'role': 'user', 'content': f'历史对话：\n{history_text}\n\n当前问题：{question}\n\n请直接用中文回答。'},
        ],
        'temperature': 0.7,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.qwen_api_base.rstrip('/')}/chat/completions",
                headers={'Authorization': f'Bearer {settings.qwen_api_key}', 'Content-Type': 'application/json'},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
    except Exception:
        logger.exception('LLM chat request failed')
        return '模型服务请求失败，请稍后重试。'
    choices = result.get('choices') if isinstance(result, dict) else None
    if isinstance(choices, list) and choices:
        message = choices[0].get('message', {}) if isinstance(choices[0], dict) else {}
        content = message.get('content') if isinstance(message, dict) else ''
        if isinstance(content, str) and content.strip():
            return content.strip()
    logger.warning('LLM chat response missing content')
    return '模型服务没有返回有效内容，请稍后重试。'
