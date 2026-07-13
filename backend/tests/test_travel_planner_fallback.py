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


def test_build_travel_plan_fallback_splits_route_and_destination_days(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = TravelPlanRequest(
        origin='济南',
        destination='成都',
        travel_mode='driving',
        preferences='途中游玩三天，到成都游玩四天，喜欢博物馆和公园',
        source_query='从济南自驾到成都，途中游玩三天，到成都游玩四天，喜欢博物馆和公园',
    )
    plan = travel_planner.build_travel_plan(request)
    assert plan.data_source == 'fallback'
    assert plan.duration_days == 7
    assert len(plan.daily_itinerary) == 7
    assert [day.stage for day in plan.daily_itinerary[:3]] == ['route', 'route', 'route']
    assert [day.stage for day in plan.daily_itinerary[3:]] == ['destination', 'destination', 'destination', 'destination']
    assert plan.raw_route['trip_profile']['route_days'] == 3
    assert plan.raw_route['trip_profile']['destination_days'] == 4
    destination_reasons = [reason for day in plan.daily_itinerary[3:] for reason in day.recommendation_reasons]
    assert any('博物馆' in reason or '公园' in reason for reason in destination_reasons)
    assert plan.raw_route['route_stops']
    assert plan.raw_route['poi_candidates']['destination_candidates']


def test_build_travel_plan_prefers_stage_sum_when_total_conflicts(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = TravelPlanRequest(
        origin='济南',
        destination='成都',
        travel_mode='driving',
        source_query='总共三天，从济南自驾到成都，途中游玩三天，到成都游玩三天',
    )
    plan = travel_planner.build_travel_plan(request)
    assert plan.duration_days == 6
    assert len(plan.daily_itinerary) == 6
    assert any('已按阶段天数重新计算' in note for note in plan.daily_itinerary[0].notes)


def test_build_travel_plan_uses_weather_context_for_daily_strategy(monkeypatch):
    from travel_agent.services import travel_planner

    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None):
        return {
            'data_source': 'fallback',
            'destination': destination,
            'summary': '成都未来几天有阵雨，建议优先安排室内景点。',
            'daily_weather': [
                {'day': 1, 'city': '郑州', 'weather': '多云', 'temperature': '24-31℃', 'outdoor_suitability': 'good', 'indoor_priority': False, 'risk_level': 'low', 'strategy': '天气适合室外游览，可安排公园、古城、步道。'},
                {'day': 2, 'city': '西安', 'weather': '阵雨', 'temperature': '23-29℃', 'outdoor_suitability': 'limited', 'indoor_priority': True, 'risk_level': 'medium', 'strategy': '有降雨风险，优先安排博物馆、美术馆、纪念馆等室内景点。'},
                {'day': 3, 'city': '成都', 'weather': '暴雨', 'temperature': '22-26℃', 'outdoor_suitability': 'poor', 'indoor_priority': True, 'risk_level': 'high', 'strategy': '暴雨天气，不建议强行安排山岳步道等户外景点。'},
                {'day': 4, 'city': '成都', 'weather': '晴', 'temperature': '22-30℃', 'outdoor_suitability': 'good', 'indoor_priority': False, 'risk_level': 'low', 'strategy': '天气适合室外游览，可安排公园、古城、步道。'},
            ],
            'warnings': [],
            'request_debug': {'provider': 'fallback', 'fallback_reason': 'test'},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = TravelPlanRequest(
        origin='济南',
        destination='成都',
        travel_mode='driving',
        source_query='从济南自驾到成都，途中游玩两天，到成都游玩两天，喜欢博物馆和公园',
    )
    plan = travel_planner.build_travel_plan(request)
    assert plan.raw_route['weather_context']['summary'] == '成都未来几天有阵雨，建议优先安排室内景点。'
    assert plan.weather_hint == plan.raw_route['weather_context']['summary']
    assert all(any('天气策略' in note for note in day.notes) for day in plan.daily_itinerary)
    rainy_reasons = [reason for day in plan.daily_itinerary if any('阵雨' in note or '暴雨' in note for note in day.notes) for reason in day.recommendation_reasons]
    assert any('天气适配' in reason or '博物馆' in reason for reason in rainy_reasons)


def test_build_travel_plan_arranges_must_visit_waypoints(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = TravelPlanRequest(
        origin='济南',
        destination='成都',
        travel_mode='driving',
        source_query='从济南自驾到成都，途经西安和汉中，沿途必须去龙门石窟，到成都后必须去成都博物馆，途中游玩三天，到成都游玩三天',
        trip_profile={
            'waypoint_details': [
                {'name': '西安', 'type': 'city', 'must_visit': True, 'source': 'parsed', 'order': 1},
                {'name': '汉中', 'type': 'city', 'must_visit': True, 'source': 'parsed', 'order': 2},
                {'name': '龙门石窟', 'type': 'attraction', 'must_visit': True, 'source': 'parsed', 'order': 3},
            ],
            'must_visit_attractions': ['龙门石窟', '成都博物馆'],
            'waypoint_order_mode': 'user_order',
        },
    )
    plan = travel_planner.build_travel_plan(request)
    all_attractions = [item for day in plan.daily_itinerary for item in day.attractions]
    names = [item.get('name') for item in all_attractions]
    assert '龙门石窟' in names
    assert '成都博物馆' in names
    assert any(item.get('must_visit') == 'true' for item in all_attractions if item.get('name') in {'龙门石窟', '成都博物馆'})
    route_stop_names = [item['name'] for item in plan.raw_route['route_stops']]
    assert '西安' in route_stop_names
    assert '汉中' in route_stop_names
    assert '龙门石窟' in route_stop_names
    assert '龙门石窟' in plan.raw_route['must_visit_attractions']
    assert '成都博物馆' in plan.raw_route['must_visit_attractions']
