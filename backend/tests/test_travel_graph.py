import pytest

from travel_agent.agent.travel_graph import unified_graph
from travel_agent.models.travel import RouteOption, RouteStep, TravelPlanResponse
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
    assert state['route_context']['stage_segments']
    assert plan['raw_route']['stage_segments']
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


@pytest.mark.asyncio
async def test_unified_graph_does_not_fetch_route_options_twice(monkeypatch):
    from travel_agent.agent import travel_graph

    calls = {'fetch_route_options': 0}
    option = RouteOption(
        title='兜底驾车方案',
        summary='兜底驾车方案，整体耗时约30分钟，距离约20.0km。',
        distance='20.0km',
        duration='30分钟',
        reasons=['测试路线'],
        steps=[RouteStep(instruction='出发')],
        mode='DRIVING',
    )

    def fake_fetch_route_options(request, profile):
        calls['fetch_route_options'] += 1
        return [option], 'fallback', 'test fallback', {'reason': 'test', 'destination_point': '32.0,118.0'}

    def fake_compose_travel_plan(**kwargs):
        return TravelPlanResponse(
            conversation_id=kwargs['request'].conversation_id or 'graph-no-duplicate',
            intent='travel_planning',
            scenario='travel_tourism',
            summary='已基于图节点结果生成行程。',
            route_title='济南 → 南京 旅游规划方案',
            route_options=kwargs['route_options'],
            daily_itinerary=kwargs['daily_itinerary'],
            raw_route={'weather_context': kwargs['weather_context'], 'location_debug': kwargs['location_debug']},
            data_source=kwargs['data_source'],
            route_error=kwargs['route_error'],
        )

    monkeypatch.setattr(travel_graph, 'planner_fetch_route_options', fake_fetch_route_options)
    monkeypatch.setattr(travel_graph, 'compose_travel_plan', fake_compose_travel_plan)
    state = await unified_graph.ainvoke(
        {
            'request': ChatRequest(question='从济南自驾到南京三天两晚，沿途想看博物馆和公园'),
            'conversation_id': 'graph-no-duplicate',
        }
    )

    assert state['answer_type'] == 'travel_planning'
    assert state['final_answer'] == '已基于图节点结果生成行程。'
    assert calls['fetch_route_options'] == 1


@pytest.mark.asyncio
async def test_unified_graph_keeps_xuzhou_stopover_as_route_segment(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    state = await unified_graph.ainvoke(
        {
            'request': ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'),
            'conversation_id': 'test-graph-xuzhou-stopover',
        }
    )

    plan = state['data']['travel_plan']
    assert any(stop['name'] == '徐州' for stop in plan['raw_route']['route_stops'])
    assert plan['raw_route']['stage_segments'][0]['route_segment'] == '济南 → 徐州'
    assert plan['daily_itinerary'][0]['anchor_city'] == '徐州'
    assert plan['daily_itinerary'][-1]['stage'] == 'destination'
    assert plan['daily_itinerary'][-1]['anchor_city'] == '杭州'
