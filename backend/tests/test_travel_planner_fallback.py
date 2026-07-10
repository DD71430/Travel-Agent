from travel_agent.models.travel import TravelPlanRequest
from travel_agent.services import travel_planner


def test_build_travel_plan_fallback_without_tencent_key(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = TravelPlanRequest(
        origin='济南',
        destination='南京',
        travel_mode='driving',
        preferences='沿途想看博物馆和公园',
        source_query='从济南自驾到南京三天两晚，沿途想看博物馆和公园',
        trip_profile={'duration_days': 3, 'interest_tags': ['博物馆', '公园'], 'pace': 'normal'},
    )
    plan = travel_planner.build_travel_plan(request)
    assert plan.data_source == 'fallback'
    assert plan.trip_type == 'along_route_trip'
    assert len(plan.daily_itinerary) == 3
    assert plan.raw_route['request_debug']['interest_tags'] == ['博物馆', '公园']
