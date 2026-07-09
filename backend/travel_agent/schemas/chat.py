from __future__ import annotations

from pydantic import BaseModel, Field


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
