from fastapi import APIRouter

from .chat import router as chat_router
from travel_agent.models.travel import TravelPlanRequest, TravelPlanResponse
from travel_agent.services.travel_planner import TencentMapsError, build_travel_plan

router = APIRouter(tags=['travel'])
router.include_router(chat_router)


@router.post('/plan', response_model=TravelPlanResponse)
def plan_travel(request: TravelPlanRequest) -> TravelPlanResponse:
    try:
        return build_travel_plan(request)
    except TencentMapsError:
        raise
