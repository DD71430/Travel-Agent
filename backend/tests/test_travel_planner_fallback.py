from travel_agent.models.travel import TravelPlanRequest, Waypoint
from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.request_builder import build_travel_request
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


def test_fallback_routes_keep_requested_mode_and_honest_reason(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    expected = {
        'driving': ('DRIVING', '驾车', '未获取真实驾车路线'),
        'walking': ('WALKING', '步行', '未获取真实步行路线'),
        'bicycling': ('BICYCLING', '骑行', '未获取真实骑行路线'),
        'transit': ('TRANSIT', '公交', '未获取到真实公交路线'),
    }
    for mode, (route_mode, title_text, reason_text) in expected.items():
        request = TravelPlanRequest(origin='济南', destination='南京', travel_mode=mode)
        routes = travel_planner._fallback_routes(request, 'travel_tourism', 'missing_key')
        assert routes[0].mode == route_mode
        assert title_text in routes[0].title
        assert any(reason_text in reason for reason in routes[0].reasons)


def test_waypoint_order_preserves_user_input_order():
    request = TravelPlanRequest(
        origin='济南',
        destination='南京',
        travel_mode='driving',
        waypoint_order=True,
        waypoints=[Waypoint(name='曲阜'), Waypoint(name='泰安')],
    )
    assert travel_planner._sort_waypoints(request) == ['曲阜', '泰安']


def test_non_driving_waypoint_order_reports_unsupported_warning(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', 'fake-key')
    request = TravelPlanRequest(
        origin='济南',
        destination='南京',
        travel_mode='walking',
        waypoint_order=True,
        waypoints=[Waypoint(name='曲阜'), Waypoint(name='泰安')],
    )

    monkeypatch.setattr(travel_planner, '_resolve_location_point', lambda address, region=None: ('36.0,117.0', 'geocoder'))

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'status': 1, 'message': 'forced fallback'}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params=None):
            assert params['waypoints'] == '36.0,117.0;36.0,117.0'
            assert 'waypoint_order' not in params
            return FakeResponse()

    monkeypatch.setattr(travel_planner.httpx, 'Client', FakeClient)
    _, data_source, route_error, location_debug = travel_planner.fetch_route_options(request, {})
    assert data_source == 'fallback'
    assert route_error
    assert any('当前交通方式不支持途经点自动排序' in warning for warning in location_debug.get('warnings', []))


def test_region_center_geocode_returns_low_confidence_fallback(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', 'fake-key')
    request = TravelPlanRequest(origin='未知详细地址A', destination='未知详细地址B', travel_mode='driving')
    monkeypatch.setattr(travel_planner, '_resolve_location_point', lambda address, region=None: ('36.0,117.0', 'region_center'))

    routes, data_source, route_error, location_debug = travel_planner.fetch_route_options(request, {})
    assert routes
    assert data_source == 'fallback'
    assert location_debug['origin_quality'] == 'low'
    assert location_debug['destination_quality'] == 'low'
    assert '城市中心' in route_error


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


def test_build_stage_segments_for_stopover_then_destination():
    question = '从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'
    request = build_travel_request(ChatRequest(question=question))
    profile = travel_planner._extract_trip_profile(request)
    route_context = {
        'route_total_duration_minutes': 584,
        'route_total_distance_meters': 857_500,
        'data_source': 'fallback',
        'stage_counts': {
            'total_days': 3,
            'route_days': 2,
            'destination_days': 1,
            'buffer_days': 0,
            'stage_plan_mode': 'route_then_destination',
            'stage_notes': [],
        },
    }

    segments = travel_planner.build_stage_segments(request, profile, route_context)

    assert [item['route_segment'] for item in segments] == ['济南 → 徐州', '徐州 → 杭州', '杭州市内/周边']
    assert segments[0]['anchor_city'] == '徐州'
    assert segments[1]['anchor_city'] == '杭州'
    assert segments[2]['stage'] == 'destination'
    assert segments[2]['drive_minutes'] <= 60


def test_build_travel_plan_uses_stopover_stage_segments(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = build_travel_request(
        ChatRequest(question='帮我规划一个从济南到杭州三天两晚的旅行路线，要求自驾，在徐州停留一天，剩余时间在杭州游玩，优先经典景点和合理游览节奏')
    )

    plan = travel_planner.build_travel_plan(request)

    route_stop_names = [item['name'] for item in plan.raw_route['route_stops']]
    assert '徐州' in route_stop_names
    assert plan.raw_route['stage_segments'][0]['route_segment'] == '济南 → 徐州'
    assert plan.raw_route['stage_segments'][1]['route_segment'] == '徐州 → 杭州'
    assert plan.daily_itinerary[0].stage == 'route'
    assert plan.daily_itinerary[0].anchor_city == '徐州'
    assert '徐州' in plan.daily_itinerary[0].route_segment
    assert plan.daily_itinerary[-1].stage == 'destination'
    assert plan.daily_itinerary[-1].anchor_city == '杭州'
    assert '整体通行约' not in ' '.join(plan.daily_itinerary[-1].notes)
    assert not any('杭州目的地深度游' in day.title for day in plan.daily_itinerary[:2])


def test_fallback_weather_does_not_claim_rain_or_heat_adaptation(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None):
        return {
            'data_source': 'fallback',
            'destination': destination,
            'summary': '天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。',
            'daily_weather': [
                {'day': 1, 'city': '徐州', 'weather': '阵雨', 'temperature': '36℃', 'outdoor_suitability': 'limited', 'indoor_priority': True, 'risk_level': 'medium', 'strategy': '天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。'},
                {'day': 2, 'city': '杭州', 'weather': '阵雨', 'temperature': '36℃', 'outdoor_suitability': 'limited', 'indoor_priority': True, 'risk_level': 'medium', 'strategy': '天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。'},
                {'day': 3, 'city': '杭州', 'weather': '阵雨', 'temperature': '36℃', 'outdoor_suitability': 'limited', 'indoor_priority': True, 'risk_level': 'medium', 'strategy': '天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。'},
            ],
            'warnings': ['weather_fallback'],
            'request_debug': {'provider': 'fallback', 'fallback_reason': 'test'},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'))

    plan = travel_planner.build_travel_plan(request)

    day_text = ' '.join(
        ' '.join([day.morning, day.afternoon, day.evening, *day.notes, *day.recommendation_reasons])
        for day in plan.daily_itinerary
    )
    assert '雨天/高温适配' not in day_text
    assert '雨天优先室内' not in day_text
    assert '室内优先' not in day_text
    assert '天气待确认' in day_text


def test_tencent_rain_weather_can_prioritize_indoor(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None):
        return {
            'data_source': 'tencent_maps',
            'destination': destination,
            'summary': '杭州未来3天天气参考：阵雨；建议优先安排室内景点。',
            'daily_weather': [
                {'day': 1, 'city': '徐州', 'weather': '阵雨', 'temperature': '24-28℃', 'outdoor_suitability': 'limited', 'indoor_priority': True, 'risk_level': 'medium', 'strategy': '雨天优先室内，室外景点建议视天气压缩停留。'},
                {'day': 2, 'city': '杭州', 'weather': '阵雨', 'temperature': '24-28℃', 'outdoor_suitability': 'limited', 'indoor_priority': True, 'risk_level': 'medium', 'strategy': '雨天优先室内，室外景点建议视天气压缩停留。'},
                {'day': 3, 'city': '杭州', 'weather': '阵雨', 'temperature': '24-28℃', 'outdoor_suitability': 'limited', 'indoor_priority': True, 'risk_level': 'medium', 'strategy': '雨天优先室内，室外景点建议视天气压缩停留。'},
            ],
            'warnings': [],
            'request_debug': {'provider': 'tencent_maps', 'fallback_reason': None},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩，喜欢博物馆和公园'))

    plan = travel_planner.build_travel_plan(request)

    assert any('雨天优先室内' in reason for day in plan.daily_itinerary for reason in day.recommendation_reasons + day.notes)


def test_daily_notes_do_not_duplicate_meals_hotels_or_reasons(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'))

    plan = travel_planner.build_travel_plan(request)

    first_day = plan.daily_itinerary[0]
    note_text = ' '.join(first_day.notes)
    assert '午餐' not in note_text
    assert '晚餐' not in note_text
    assert '住宿' not in note_text
    assert len(first_day.recommendation_reasons) == len(set(first_day.recommendation_reasons))
    assert len(first_day.tags) == len(set(first_day.tags))


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
    assert plan.weather_hint == '成都天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。'
    assert all(any('天气策略' in note for note in day.notes) for day in plan.daily_itinerary)
    day_text = ' '.join(' '.join([day.morning, day.afternoon, day.evening, *day.notes, *day.recommendation_reasons]) for day in plan.daily_itinerary)
    assert '雨天/高温适配' not in day_text
    assert '雨天优先室内' not in day_text
    assert '室内优先' not in day_text


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
