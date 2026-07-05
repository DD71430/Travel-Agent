from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import ffmpeg
import httpx
from fastapi import UploadFile
from pydantic import BaseModel, Field
from pypdf import PdfReader

from travel_agent.core.config import get_settings
from travel_agent.memory.redis_memory import RedisMemoryStore
from travel_agent.models.travel import TravelPlanRequest
from travel_agent.tools.tencent_webservice_client import TencentWebServiceClient

NEARBY_KEYWORDS = ('附近', '周边', '酒店', '餐厅', '美食', '景点', '博物馆', '公园', '商场', '推荐')
settings = get_settings()
memory_store = RedisMemoryStore()
_client = TencentWebServiceClient()

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    conversation_id: str | None = None
    image_context: str | None = None
    origin: str | None = None
    destination: str | None = None
    preferences: str | None = None
    travel_mode: str | None = None
    waypoint_order: bool | None = None
    waypoints_json: str | None = None
    force_current_anchor: bool | None = None

# simplified: reuse exact helpers by importing from api.chat would cause cycles
# so only the orchestration helpers live here.


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


def build_travel_request(request: ChatRequest) -> TravelPlanRequest:
    from travel_agent.api.chat import _build_travel_request as _impl
    return _impl(request)


def build_nearby_response(request: ChatRequest) -> dict:
    from travel_agent.api.chat import _build_nearby_response as _impl
    return _impl(request)


def classify_chat_intent(question: str) -> str:
    from travel_agent.api.chat import _classify_chat_intent as _impl
    return _impl(question)


async def generate_general_answer(question: str, conversation_id: str) -> str:
    from travel_agent.api.chat import _generate_general_answer as _impl
    return await _impl(question, conversation_id)
