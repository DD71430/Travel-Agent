import pytest

from travel_agent.agent.travel_graph import unified_graph
from travel_agent.schemas.chat import ChatRequest
from travel_agent.services import travel_planner


@pytest.mark.asyncio
async def test_unified_graph_builds_stage_split_travel_plan_without_tencent_key(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    state = await unified_graph.ainvoke(
        {
            'request': ChatRequest(question='从济南自驾到成都，途中游玩三天，到成都游玩四天，喜欢博物馆和公园'),
            'conversation_id': 'test-graph-stage-split',
        }
    )
    plan = state['data']['travel_plan']
    assert state['answer_type'] == 'travel_planning'
    assert plan['duration_days'] == 7
    assert [item['stage'] for item in plan['daily_itinerary'][:3]] == ['route', 'route', 'route']
    assert [item['stage'] for item in plan['daily_itinerary'][3:]] == ['destination', 'destination', 'destination', 'destination']
    assert state['route_options']
    assert state['poi_candidates']['route_candidates']
    assert state['ranked_pois']['destination_candidates']
    assert state['weather_context']
    assert plan['raw_route']['weather_context']
    assert 'route_options_fetched' in state['processing_notes']


@pytest.mark.asyncio
async def test_unified_graph_keeps_must_visit_waypoints_without_tencent_key(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    state = await unified_graph.ainvoke(
        {
            'request': ChatRequest(question='从济南自驾到成都，途经西安和汉中，沿途必须去龙门石窟，到成都后必须去成都博物馆，途中游玩三天，到成都游玩三天'),
            'conversation_id': 'test-graph-waypoints',
        }
    )
    plan = state['data']['travel_plan']
    names = [item.get('name') for day in plan['daily_itinerary'] for item in day.get('attractions', [])]
    assert state['answer_type'] == 'travel_planning'
    assert '龙门石窟' in names
    assert '成都博物馆' in names
    assert plan['raw_route']['waypoint_details']
    assert '龙门石窟' in plan['raw_route']['must_visit_attractions']
