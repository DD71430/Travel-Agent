import pytest

from travel_agent.agent.travel_graph import unified_graph
from travel_agent.agent.planner import PlannerNode
from travel_agent.models.travel import RouteOption, RouteStep, TravelPlanResponse
from travel_agent.schemas.chat import ChatRequest
from travel_agent.services import travel_planner


def test_legacy_planner_keeps_commute_when_company_context_uses_subway():
    state = PlannerNode()({'question': '从家到公司地铁怎么走'})

    assert state['scenario'] == 'daily_commute'


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


@pytest.mark.asyncio
async def test_unified_graph_passes_daily_city_allocation_to_weather(monkeypatch):
    from travel_agent.agent import travel_graph

    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    captured: dict[str, object] = {}

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None, daily_plan_context=None):
        captured['daily_plan_context'] = daily_plan_context
        anchors = [str(item.get('anchor_city') or destination) for item in daily_plan_context or []]
        return {
            'data_source': 'tencent_maps',
            'destination': destination,
            'summary': '测试天气',
            'daily_weather': [
                {
                    'day': index,
                    'city': city,
                    'weather': '多云',
                    'temperature': '20-28℃',
                    'data_source': 'tencent_maps',
                    'weather_tags': [],
                    'weather_tips': [],
                    'packing_tips': [],
                }
                for index, city in enumerate(anchors, start=1)
            ],
            'warnings': [],
            'request_debug': {'provider': 'test'},
        }

    monkeypatch.setattr(travel_graph, 'build_weather_context', fake_weather_context)
    state = await unified_graph.ainvoke(
        {
            'request': ChatRequest(
                question='帮我规划一个从杭州到济南三天两晚的旅行路线，要求乘坐高铁，在徐州游玩两天，剩余时间在济南游玩，优先经典景点和合理游览节奏'
            ),
            'conversation_id': 'test-graph-daily-weather-targets',
        }
    )

    plan = state['data']['travel_plan']
    assert plan['duration_days'] == 3
    assert [item['anchor_city'] for item in plan['daily_itinerary']] == ['徐州', '徐州', '济南']
    assert [item['anchor_city'] for item in captured['daily_plan_context']] == ['徐州', '徐州', '济南']
