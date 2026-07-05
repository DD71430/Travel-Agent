from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str
    chat_history: list[dict[str, str]]
    user_profile: dict[str, Any]
    intent: str
    scenario: str
    plan: list[str]
    retrieved_docs: list[dict[str, Any]]
    tool_results: dict[str, Any]
    memory_context: dict[str, Any]
    draft_answer: str
    reflection_result: dict[str, Any]
    final_answer: str
    iteration: int
    conversation_id: str
    image_context: dict[str, Any] | None
    route_reply: dict[str, Any]
    location_entities: dict[str, str]
    route_request: dict[str, Any]
    route_summary: str
    retry_reason: str
    processing_notes: list[str]
