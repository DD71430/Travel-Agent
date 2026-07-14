from fastapi import APIRouter

from .chat import memory_store, router as chat_router
from travel_agent.models.travel import TravelPlanRequest, TravelPlanResponse
from travel_agent.services.travel_planner import TencentMapsError, build_travel_plan

router = APIRouter(tags=['travel'])
router.include_router(chat_router)


@router.post('/plan', response_model=TravelPlanResponse)
def plan_travel(request: TravelPlanRequest) -> TravelPlanResponse:
    try:
        response = build_travel_plan(request, memory_store_override=memory_store)
        memory_store.append_turn(response.conversation_id, f'{request.origin} -> {request.destination}', response.summary)
        memory_store.update_conversation_meta(response.conversation_id, intent=response.intent)
        return response
    except TencentMapsError:
        raise
