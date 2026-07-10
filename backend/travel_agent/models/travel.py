from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Waypoint(BaseModel):
    name: str = Field(..., description='途经点名称或坐标')


class TravelPlanRequest(BaseModel):
    origin: str = Field(..., description='出发地')
    destination: str = Field(..., description='目的地')
    travel_mode: Literal['driving', 'walking', 'transit', 'bicycling'] = 'driving'
    preferences: Optional[str] = Field(default=None, description='日常出行或旅行偏好')
    source_query: Optional[str] = Field(default=None, description='用户原始输入，用于提取天数、预算等旅行信息')
    conversation_id: Optional[str] = Field(default=None, description='会话 ID，用于多轮对话记忆')
    waypoints: list[Waypoint] = Field(default_factory=list, description='途经点列表')
    waypoint_order: bool = Field(default=False, description='是否让服务端智能排序途经点')
    request_source: Literal['sidebar', 'chat'] = 'sidebar'
    trip_profile: dict[str, Any] = Field(default_factory=dict, description='结构化旅行需求')


class UnifiedResponseData(BaseModel):
    travel_plan: dict | None = None
    weather: dict | None = None
    nearby: dict | None = None


class UnifiedChatResponse(BaseModel):
    conversation_id: str
    answer_type: str
    final_answer: str
    data: UnifiedResponseData = Field(default_factory=UnifiedResponseData)
    travel_request: dict | None = None
    upload_context: dict | None = None
    meta: dict = Field(default_factory=dict)
    error: str | None = None


class RouteStep(BaseModel):
    instruction: str
    distance: str | None = None
    duration: str | None = None
    road_name: str | None = None
    direction: str | None = None
    action: str | None = None


class RouteOption(BaseModel):
    title: str
    summary: str
    distance: str
    duration: str
    reasons: list[str]
    steps: list[RouteStep]
    mode: str | None = None
    tags: list[str] = Field(default_factory=list)
    toll: int | float | None = None
    traffic_light_count: int | None = None
    waypoint_summary: str | None = None


class TripDayPlan(BaseModel):
    day: int
    title: str
    route_segment: str | None = None
    drive_time: str | None = None
    visit_time: str | None = None
    morning: str
    afternoon: str
    evening: str
    attractions: list[dict[str, str]] = Field(default_factory=list)
    meals: list[str] = Field(default_factory=list)
    hotel_hint: str | None = None
    recommendation_reasons: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConversationTurn(BaseModel):
    user_input: str
    assistant_output: str


class TravelPlanResponse(BaseModel):
    conversation_id: str
    intent: str
    scenario: str
    summary: str
    route_title: str
    trip_type: str = 'destination_trip'
    route_total_duration: str = ''
    route_total_distance: str = ''
    trip_overview: str = ''
    duration_days: int = 3
    budget_estimate: str = '待估算'
    accommodation_suggestion: str = ''
    transportation_suggestion: list[str] = Field(default_factory=list)
    weather_hint: str = ''
    attraction_recommendations: list[str] = Field(default_factory=list)
    hotel_candidates: list[dict[str, str]] = Field(default_factory=list)
    food_candidates: list[dict[str, str]] = Field(default_factory=list)
    scenic_route_highlights: list[str] = Field(default_factory=list)
    daily_itinerary: list[TripDayPlan] = Field(default_factory=list)
    travel_tips: list[str] = Field(default_factory=list)
    route_steps: list[RouteStep] = Field(default_factory=list)
    route_options: list[RouteOption] = Field(default_factory=list)
    recommendation_reasons: list[str] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)
    history: list[ConversationTurn] = Field(default_factory=list)
    raw_route: dict = Field(default_factory=dict)
    data_source: str = 'fallback'
    confidence: str = 'medium'
    route_error: str | None = None
