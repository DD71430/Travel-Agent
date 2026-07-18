from travel_agent.models.travel import TravelPlanRequest, Waypoint
from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.request_builder import build_travel_request
from travel_agent.services import travel_planner


COMPREHENSIVE_HANGZHOU_QUESTION = (
    '帮我规划一个从济南出发到杭州的 5 天 4 晚旅行方案，乘高铁跨城，市内以地铁和打车为主。'
    '途中希望在徐州停留 1 天，顺路去徐州博物馆和云龙湖；'
    '到杭州后玩 3 天，必须安排西湖、浙江省博物馆、灵隐寺和河坊街。'
    '同行有老人和一个小朋友，节奏轻松一点，少走路，不爬山，偏好历史文化、博物馆、经典景点和本地美食。'
    '预算控制在 6000 元左右。请结合未来天气安排每天上午、下午、晚上行程，推荐每天附近餐厅和住宿区域，'
    '并说明交通方式、天气调整、装备建议和哪些景点需要提前预约。'
)


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


def test_build_travel_plan_keeps_explicit_total_when_stage_sum_conflicts(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = TravelPlanRequest(
        origin='济南',
        destination='成都',
        travel_mode='driving',
        source_query='总共三天，从济南自驾到成都，途中游玩三天，到成都游玩三天',
    )
    plan = travel_planner.build_travel_plan(request)
    assert plan.duration_days == 3
    assert len(plan.daily_itinerary) == 3
    assert any('冲突' in note and '3天' in note for note in plan.daily_itinerary[0].notes)


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
            'route_days': 1,
            'destination_days': 2,
            'buffer_days': 0,
            'stage_plan_mode': 'route_then_destination',
            'stage_notes': [],
        },
    }

    segments = travel_planner.build_stage_segments(request, profile, route_context)

    assert [item['route_segment'] for item in segments] == ['济南 → 徐州', '徐州 → 杭州', '杭州市内/周边']
    assert segments[0]['anchor_city'] == '徐州'
    assert segments[1]['anchor_city'] == '杭州'
    assert segments[1]['stage'] == 'destination'
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


def test_high_speed_rail_plan_uses_transport_block_instead_of_driving_copy(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = build_travel_request(
        ChatRequest(question='帮我规划一个从济南到杭州三天两晚的旅行路线，要求乘坐高铁，在徐州游玩一天，剩余时间在杭州游玩，优先经典景点和合理游览节奏')
    )

    plan = travel_planner.build_travel_plan(request)

    assert plan.raw_route['trip_profile']['intercity_mode'] == 'high_speed_rail'
    assert plan.raw_route['trip_profile']['local_mode'] == 'mixed'
    assert plan.raw_route['stage_segments'][0]['transport_block']['mode'] == 'high_speed_rail'
    first_day_text = ' '.join([plan.daily_itinerary[0].morning, plan.daily_itinerary[0].evening, *plan.daily_itinerary[0].notes])
    assert '高铁' in first_day_text
    assert '进站候车' in first_day_text
    assert '出站接驳' in first_day_text
    assert '驾驶' not in first_day_text
    assert any('高铁' in item for item in plan.transportation_suggestion)


def test_high_speed_rail_summary_mentions_parsed_stopover_and_weather_targets(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = build_travel_request(
        ChatRequest(question='帮我规划一个从济南到杭州三天两晚的旅行路线，要求乘坐高铁，在徐州游玩一天，剩余时间在杭州游玩，优先经典景点和合理游览节奏，请查询天气')
    )

    plan = travel_planner.build_travel_plan(request)

    assert '途经安排：徐州' in plan.summary
    assert plan.raw_route['weather_context']['request_debug']['weather_targets'][0]['city'] == '徐州'
    scheduled_names = [item['name'] for day in plan.daily_itinerary for item in day.attractions]
    assert any('徐州' in name for name in scheduled_names)
    assert any('杭州' in name or name in {'西湖风景名胜区', '灵隐寺'} for name in scheduled_names)
    for name in scheduled_names:
        assert name in plan.attraction_recommendations


def test_explicit_three_day_trip_repeats_two_day_stopover_before_destination(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    captured: dict[str, object] = {}

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None, daily_plan_context=None):
        captured['days'] = days
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
                    'strategy': '适合常规游览。',
                    'weather_tips': [],
                    'packing_tips': [],
                    'weather_tags': [],
                    'indoor_priority': False,
                    'outdoor_suitability': 'good',
                    'risk_level': 'low',
                    'data_source': 'tencent_maps',
                    'fallback_reason': None,
                }
                for index, city in enumerate(anchors, start=1)
            ],
            'warnings': [],
            'request_debug': {'provider': 'test'},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = build_travel_request(
        ChatRequest(question='帮我规划一个从杭州到济南三天两晚的旅行路线，要求乘坐高铁，在徐州游玩两天，剩余时间在济南游玩，优先经典景点和合理游览节奏')
    )

    plan = travel_planner.build_travel_plan(request)

    assert plan.duration_days == 3
    assert len(plan.daily_itinerary) == 3
    assert [day.anchor_city for day in plan.daily_itinerary] == ['徐州', '徐州', '济南']
    assert [day.stage for day in plan.daily_itinerary] == ['route', 'route', 'destination']
    assert captured['days'] == 3
    assert [item['anchor_city'] for item in captured['daily_plan_context']] == ['徐州', '徐州', '济南']
    assert plan.raw_route['trip_profile']['duration_source'] == 'explicit_duration'
    assert plan.raw_route['route_context']['stage_counts']['buffer_days'] == 0


def test_weather_binding_rejects_same_day_weather_for_wrong_city():
    day_context = {'day': 1, 'anchor_city': '徐州'}
    weather_days = [
        {'day': 1, 'city': '济南', 'weather': '晴', 'data_source': 'tencent_maps'},
        {'day': 2, 'city': '徐州', 'weather': '小雨', 'data_source': 'tencent_maps'},
    ]

    assert travel_planner.find_weather_day_for_context(day_context, weather_days, 0) is None


def test_weather_binding_uses_day_and_city_when_weather_array_is_unordered():
    day_context = {'day': 2, 'anchor_city': '徐州'}
    weather_days = [
        {'day': 3, 'city': '济南', 'weather': '晴', 'data_source': 'tencent_maps'},
        {'day': 2, 'city': '济南', 'weather': '多云', 'data_source': 'tencent_maps'},
        {'day': 2, 'city': '徐州市', 'weather': '小雨', 'data_source': 'tencent_maps'},
    ]

    matched = travel_planner.find_weather_day_for_context(day_context, weather_days, 1)

    assert matched is not None
    assert matched['city'] == '徐州市'
    assert matched['weather'] == '小雨'


def test_weather_context_uses_daily_anchor_cities_when_fetching_weather(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    captured: dict[str, object] = {}

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None, daily_plan_context=None):
        captured['route_stops'] = route_stops
        captured['daily_plan_context'] = daily_plan_context
        return {
            'data_source': 'fallback',
            'destination': destination,
            'summary': '天气待确认',
            'daily_weather': [
                {'day': 1, 'city': '徐州', 'weather': '天气待确认', 'temperature': '温度待确认', 'data_source': 'fallback'},
                {'day': 2, 'city': '杭州', 'weather': '天气待确认', 'temperature': '温度待确认', 'data_source': 'fallback'},
                {'day': 3, 'city': '杭州', 'weather': '天气待确认', 'temperature': '温度待确认', 'data_source': 'fallback'},
            ],
            'warnings': ['weather_fallback'],
            'request_debug': {'provider': 'fallback', 'fallback_reason': 'test'},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'))

    plan = travel_planner.build_travel_plan(request)

    daily_context = captured['daily_plan_context']
    assert isinstance(daily_context, list)
    assert [item['anchor_city'] for item in daily_context] == ['徐州', '杭州', '杭州']
    assert [day.anchor_city for day in plan.daily_itinerary] == ['徐州', '杭州', '杭州']


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


def test_rain_weather_reorders_candidate_pois_before_daily_selection(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None, daily_plan_context=None):
        cities = ['徐州', '杭州', '杭州']
        return {
            'data_source': 'tencent_maps',
            'destination': destination,
            'summary': '未来3天有降雨，优先室内景点。',
            'daily_weather': [
                {
                    'day': index,
                    'city': cities[index - 1],
                    'weather': '阵雨',
                    'temperature': '24-28℃',
                    'outdoor_suitability': 'limited',
                    'indoor_priority': True,
                    'risk_level': 'medium',
                    'strategy': '雨天优先室内，室外景点建议视天气压缩停留。',
                    'weather_tags': ['rain'],
                }
                for index in range(1, days + 1)
            ],
            'warnings': [],
            'request_debug': {'provider': 'tencent_maps', 'fallback_reason': None},
        }

    def fake_candidates_for_day(**kwargs):
        anchor_city = kwargs.get('anchor_city') or '杭州'
        outdoor_name = '云龙湖风景区' if anchor_city == '徐州' else '西湖风景名胜区'
        return [
            {'name': outdoor_name, 'category': '风景名胜;公园', 'address': f'{anchor_city}核心区', 'estimated_minutes': '120'},
            {'name': f'{anchor_city}博物馆', 'category': '博物馆', 'address': f'{anchor_city}核心区', 'estimated_minutes': '150'},
            {'name': f'{anchor_city}美术馆', 'category': '美术馆', 'address': f'{anchor_city}核心区', 'estimated_minutes': '120'},
        ]

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    monkeypatch.setattr(travel_planner, '_candidate_pois_for_day', fake_candidates_for_day)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩，喜欢公园和博物馆'))

    plan = travel_planner.build_travel_plan(request)

    first_name = plan.daily_itinerary[0].attractions[0]['name']
    assert any(keyword in first_name for keyword in ('博物馆', '美术馆'))
    assert '云龙湖' not in first_name
    assert '西湖' not in first_name
    first_day_text = ' '.join([plan.daily_itinerary[0].morning, *plan.daily_itinerary[0].recommendation_reasons])
    assert '雨天优先室内' in first_day_text


def test_tencent_rain_weather_is_visible_in_plan_summary_and_daily_fields(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None):
        return {
            'data_source': 'tencent_maps',
            'destination': destination,
            'summary': '杭州未来3天天气参考：阵雨；建议优先安排室内景点。',
            'daily_weather': [
                {
                    'day': index,
                    'city': '徐州' if index == 1 else '杭州',
                    'weather': '阵雨',
                    'temperature': '22-28℃',
                    'outdoor_suitability': 'limited',
                    'indoor_priority': True,
                    'risk_level': 'medium',
                    'strategy': '有降雨风险，优先安排博物馆、美术馆、纪念馆等室内景点，室外景点压缩游览。',
                    'weather_tags': ['rain'],
                    'weather_tips': ['有降雨风险，建议携带雨伞或轻便雨衣。', '室外石板路、湖边步道或台阶区域注意防滑。'],
                    'packing_tips': ['雨伞或轻便雨衣', '防滑鞋'],
                }
                for index in range(1, days + 1)
            ],
            'warnings': [],
            'request_debug': {'provider': 'tencent_maps', 'fallback_reason': None},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩，喜欢博物馆和公园'))

    plan = travel_planner.build_travel_plan(request)

    combined = f'{plan.summary} {plan.trip_overview} {plan.weather_overview} {" ".join(plan.weather_adjustments)}'
    assert any(keyword in combined for keyword in ('雨伞', '雨衣', '防滑', '优先安排博物馆'))
    assert any('室内' in item or '遮蔽' in item for item in plan.weather_adjustments)
    assert plan.raw_route['weather_plan_summary']['weather_overview'] == plan.weather_overview
    assert plan.daily_itinerary[0].weather_summary
    assert plan.daily_itinerary[0].weather_badge == '雨天'
    assert any('雨伞' in tip or '雨衣' in tip for tip in plan.daily_itinerary[0].weather_tips)


def test_tencent_heat_weather_moves_midday_to_rest_or_indoor(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None):
        return {
            'data_source': 'tencent_maps',
            'destination': destination,
            'summary': '杭州未来3天天气参考：晴热；注意防晒补水并避开正午。',
            'daily_weather': [
                {
                    'day': index,
                    'city': '徐州' if index == 1 else '杭州',
                    'weather': '晴',
                    'temperature': '30-36℃',
                    'outdoor_suitability': 'limited',
                    'indoor_priority': True,
                    'risk_level': 'medium',
                    'strategy': '高温天气，中午安排室内景点、午餐或休整，户外景点尽量安排在上午或傍晚。',
                    'weather_tags': ['sun_exposure', 'heat'],
                    'weather_tips': ['注意防晒、补水。', '高温天气建议避开正午户外暴晒。'],
                    'packing_tips': ['防晒霜', '水杯', '遮阳帽或墨镜'],
                }
                for index in range(1, days + 1)
            ],
            'warnings': [],
            'request_debug': {'provider': 'tencent_maps', 'fallback_reason': None},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩，喜欢公园和湖边步道'))

    plan = travel_planner.build_travel_plan(request)

    combined = f'{plan.summary} {plan.weather_overview} {" ".join(plan.weather_adjustments)}'
    assert any(keyword in combined for keyword in ('防晒', '补水', '避开正午'))
    day_text = ' '.join([plan.daily_itinerary[0].morning, plan.daily_itinerary[0].afternoon, plan.daily_itinerary[0].evening, *plan.daily_itinerary[0].notes])
    assert any(keyword in day_text for keyword in ('中午安排室内', '午餐或休整', '避开正午户外暴晒'))
    assert '防晒霜' in plan.daily_itinerary[0].packing_tips
    assert '水杯' in plan.daily_itinerary[0].packing_tips
    assert plan.daily_itinerary[0].weather_badge == '高温'


def test_select_unique_day_pois_removes_duplicate_names_and_buckets():
    candidates = [
        {'name': '杭州博物馆', 'category': '博物馆'},
        {'name': '杭州博物馆', 'category': '博物馆'},
        {'name': '浙江省博物馆', 'category': '博物馆'},
        {'name': '小河直街历史文化街区', 'category': '历史文化街区'},
    ]

    selected = travel_planner.select_unique_day_pois(
        anchor_city='杭州',
        stage='destination',
        candidates=candidates,
        used_names=set(),
        used_buckets_by_day=set(),
        max_count=3,
    )

    names = [item['name'] for item in selected]
    assert names.count('杭州博物馆') == 1
    assert len([item for item in selected if travel_planner.classify_poi_bucket(item) == 'museum']) == 1


def test_daily_itinerary_avoids_generic_fillers_and_cross_day_repeats(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'))

    plan = travel_planner.build_travel_plan(request)

    attraction_names_by_day = [[item['name'] for item in day.attractions] for day in plan.daily_itinerary]
    for names in attraction_names_by_day:
        assert len(names) == len(set(names))

    all_names = [name for names in attraction_names_by_day for name in names]
    assert len(all_names) == len(set(all_names))
    assert not any('经典景点' in name or name == '杭州风景名胜区' for name in all_names)
    assert not any('综合匹配' in reason for day in plan.daily_itinerary for reason in day.recommendation_reasons)
    assert not any('经典游览强度' in note for day in plan.daily_itinerary for note in day.notes)
    assert all(len(day.recommendation_reasons) <= 3 for day in plan.daily_itinerary)
    for day in plan.daily_itinerary:
        note_text = ' '.join(day.notes)
        assert not any(reason and reason in note_text for reason in day.recommendation_reasons)


def test_limited_candidates_do_not_force_three_generic_attractions(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_candidates_for_day(**kwargs):
        return [{'name': '杭州博物馆', 'category': '博物馆', 'address': '杭州市上城区', 'estimated_minutes': '150'}]

    monkeypatch.setattr(travel_planner, '_candidate_pois_for_day', fake_candidates_for_day)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'))

    plan = travel_planner.build_travel_plan(request)

    first_day = plan.daily_itinerary[0]
    assert len(first_day.attractions) == 1
    assert not any('风景名胜区' in item['name'] or '经典景点' in item['name'] for item in first_day.attractions)
    assert any(token in f'{first_day.afternoon} {first_day.evening}' for token in ('休整', '轻量', '自由活动', '入住'))


def test_tencent_weather_tips_are_added_to_daily_plan(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None):
        return {
            'data_source': 'tencent_maps',
            'destination': destination,
            'summary': '杭州未来3天天气参考：阵雨；建议优先安排室内景点。',
            'daily_weather': [
                {
                    'day': index,
                    'city': '徐州' if index == 1 else '杭州',
                    'weather': '阵雨',
                    'temperature': '24-28℃',
                    'outdoor_suitability': 'limited',
                    'indoor_priority': True,
                    'risk_level': 'medium',
                    'strategy': '雨天优先室内，室外景点建议视天气压缩停留。',
                    'weather_tags': ['rain'],
                    'weather_tips': ['有降雨风险，建议携带雨伞或轻便雨衣。'],
                    'packing_tips': ['雨伞或轻便雨衣'],
                }
                for index in range(1, days + 1)
            ],
            'warnings': [],
            'request_debug': {'provider': 'tencent_maps', 'fallback_reason': None},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'))

    plan = travel_planner.build_travel_plan(request)

    assert 'rain' in plan.daily_itinerary[0].weather_tags
    assert any('雨伞' in tip or '雨衣' in tip for tip in plan.daily_itinerary[0].weather_tips)
    assert '雨伞或轻便雨衣' in plan.daily_itinerary[0].packing_tips


def test_tencent_heat_weather_adds_sunscreen_tips_to_daily_plan(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None):
        return {
            'data_source': 'tencent_maps',
            'destination': destination,
            'summary': '杭州未来3天天气参考：晴；注意防晒补水。',
            'daily_weather': [
                {
                    'day': index,
                    'city': '徐州' if index == 1 else '杭州',
                    'weather': '晴',
                    'temperature': '30-36℃',
                    'outdoor_suitability': 'limited',
                    'indoor_priority': True,
                    'risk_level': 'medium',
                    'strategy': '高温天气，中午避免室外，户外景点尽量安排在上午或傍晚。',
                }
                for index in range(1, days + 1)
            ],
            'warnings': [],
            'request_debug': {'provider': 'tencent_maps', 'fallback_reason': None},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'))

    plan = travel_planner.build_travel_plan(request)

    assert 'sun_exposure' in plan.daily_itinerary[0].weather_tags
    assert 'heat' in plan.daily_itinerary[0].weather_tags
    assert any('防晒' in tip or '补水' in tip for tip in plan.daily_itinerary[0].weather_tips)
    assert any('避开正午户外暴晒' in tip for tip in plan.daily_itinerary[0].weather_tips)
    assert '防晒霜' in plan.daily_itinerary[0].packing_tips
    assert '水杯' in plan.daily_itinerary[0].packing_tips


def test_fallback_weather_tips_stay_optional_not_deterministic(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None):
        return {
            'data_source': 'fallback',
            'destination': destination,
            'summary': '天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。',
            'daily_weather': [
                {
                    'day': index,
                    'city': '徐州' if index == 1 else '杭州',
                    'weather': '天气待确认',
                    'temperature': '温度待确认',
                    'outdoor_suitability': 'unknown',
                    'indoor_priority': False,
                    'risk_level': 'unknown',
                    'strategy': '天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。',
                }
                for index in range(1, days + 1)
            ],
            'warnings': ['weather_fallback'],
            'request_debug': {'provider': 'fallback', 'fallback_reason': 'test'},
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)
    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'))

    plan = travel_planner.build_travel_plan(request)

    combined = ' '.join(
        [*plan.daily_itinerary[0].weather_tags, *plan.daily_itinerary[0].weather_tips, *plan.daily_itinerary[0].packing_tips]
    )
    assert 'weather_unconfirmed' in plan.daily_itinerary[0].weather_tags
    assert '天气待确认' in combined
    assert '保留雨具、防晒和补水用品作为备选' in combined
    assert '今天下雨' not in combined
    assert '今天高温' not in combined


def test_fallback_weather_daily_plan_does_not_repeat_unconfirmed_copy(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    request = build_travel_request(ChatRequest(question='从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩'))

    plan = travel_planner.build_travel_plan(request)

    first_day = plan.daily_itinerary[0]
    visible_weather_text = ' '.join([first_day.weather_summary, first_day.weather_strategy or '', *first_day.weather_adjustments, *first_day.weather_tips, *first_day.notes])
    assert visible_weather_text.count('天气待确认') <= 1
    assert len(first_day.weather_adjustments) <= 1
    assert plan.raw_route['weather_context']['request_debug']['fallback_reason']


def test_segmented_trip_day1_weather_uses_anchor_city_not_destination(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')

    def fake_weather_context(destination, route_stops=None, days=3, location_debug=None, daily_plan_context=None):
        return {
            'data_source': 'tencent_maps',
            'destination': destination,
            'summary': '分段天气测试',
            'daily_weather': [
                {
                    'day': 2,
                    'city': '西安',
                    'weather': '多云',
                    'temperature': '25-33℃',
                    'data_source': 'tencent_maps',
                    'fallback_reason': None,
                    'weather_tags': [],
                    'weather_tips': ['天气适合常规游览。'],
                    'packing_tips': ['水杯'],
                    'outdoor_suitability': 'good',
                    'indoor_priority': False,
                    'risk_level': 'low',
                },
                {
                    'day': 1,
                    'city': '徐州市',
                    'weather': '阵雨',
                    'temperature': '24-31℃',
                    'data_source': 'tencent_maps',
                    'fallback_reason': None,
                    'weather_tags': ['rain'],
                    'weather_tips': ['有降雨风险，优先室内或遮蔽点位。'],
                    'packing_tips': ['雨伞'],
                    'outdoor_suitability': 'limited',
                    'indoor_priority': True,
                    'risk_level': 'medium',
                },
                {
                    'day': 3,
                    'city': '西安',
                    'weather': '晴',
                    'temperature': '26-34℃',
                    'data_source': 'tencent_maps',
                    'fallback_reason': None,
                    'weather_tags': ['sun_exposure'],
                    'weather_tips': ['注意防晒、补水。'],
                    'packing_tips': ['防晒霜'],
                    'outdoor_suitability': 'good',
                    'indoor_priority': False,
                    'risk_level': 'low',
                },
            ],
            'warnings': [],
            'request_debug': {
                'provider': 'tencent_maps',
                'fallback_reason': None,
                'weather_targets': [
                    {'day': 1, 'city': '徐州', 'adcode': '320300', 'data_source': 'tencent_maps'},
                    {'day': 2, 'city': '西安', 'adcode': '610100', 'data_source': 'tencent_maps'},
                    {'day': 3, 'city': '西安', 'adcode': '610100', 'data_source': 'tencent_maps'},
                ],
            },
        }

    monkeypatch.setattr(travel_planner, 'build_weather_context', fake_weather_context)

    request = build_travel_request(ChatRequest(question='帮我规划一个从杭州到西安三天两晚的旅行路线，要求乘坐高铁，在徐州游玩一天，剩余时间在西安游玩'))
    plan = travel_planner.build_travel_plan(request)

    first_day = plan.daily_itinerary[0]
    assert first_day.anchor_city == '徐州'
    assert first_day.weather_badge != '天气待确认'
    assert '徐州' in first_day.weather_summary
    assert '阵雨' in first_day.weather_summary


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


def test_comprehensive_hangzhou_plan_keeps_must_visits_city_scope_and_transfer_day(monkeypatch):
    monkeypatch.setattr(travel_planner.settings, 'tencent_maps_key', '')
    monkeypatch.setattr(travel_planner._client, 'key', '')
    request = build_travel_request(ChatRequest(question=COMPREHENSIVE_HANGZHOU_QUESTION))

    plan = travel_planner.build_travel_plan(request)

    assert plan.scenario == 'travel_tourism'
    required = {'西湖', '浙江省博物馆', '灵隐寺', '河坊街'}
    assert required.issubset(set(plan.raw_route['must_visit_attractions']))

    scheduled_names = {item.get('name') for day in plan.daily_itinerary for item in day.attractions}
    backup_names = {item.get('name') for day in plan.daily_itinerary for item in day.backup_attractions}
    scheduled_or_unscheduled = scheduled_names | backup_names | set(plan.raw_route['unscheduled_waypoints'])
    assert required.issubset(scheduled_or_unscheduled)

    day1 = plan.daily_itinerary[0]
    assert day1.anchor_city == '徐州'
    day1_text = ' '.join(
        [
            *[item.get('name', '') for item in day1.attractions],
            *[item.get('name', '') for item in day1.backup_attractions],
            *day1.notes,
            *plan.raw_route.get('unscheduled_waypoints', []),
            *[item.get('name', '') for item in plan.raw_route.get('backup_waypoints', [])],
        ]
    )
    assert '徐州博物馆' in day1_text
    assert '云龙湖' in day1_text

    destination_days = [day for day in plan.daily_itinerary[1:] if day.anchor_city == '杭州']
    assert destination_days
    for day in destination_days:
        names = [item.get('name', '') for item in day.attractions]
        assert not any('徐州' in name or '云龙湖' in name for name in names)

    day2 = plan.daily_itinerary[1]
    assert day2.route_segment == '徐州 → 杭州'
    assert '15:' not in day1.morning
    assert '14:' not in day2.morning
    assert '徐州 → 杭州' in day2.morning or '高铁/动车跨城' in day2.morning or '跨城转场' in day2.morning
    assert any(keyword in f'{day2.afternoon} {day2.evening}' for keyword in ('浙江省博物馆', '入住', '休整'))
    assert not day2.morning.lstrip().startswith(('杭州博物馆', '西湖', '浙江省博物馆', '灵隐寺', '河坊街'))
    assert len(day2.attractions) <= 2

    stage_segments = plan.raw_route['stage_segments']
    intercity_minutes = sum(
        int((item.get('transport_block') or {}).get('total_minutes') or 0)
        for item in stage_segments
        if (item.get('transport_block') or {}).get('origin') != (item.get('transport_block') or {}).get('destination')
    )
    assert plan.raw_route['total_intercity_minutes'] >= intercity_minutes
    assert plan.raw_route['total_transport_minutes'] >= intercity_minutes

    reservation_text = ' '.join(plan.raw_route['reservation_tips'])
    assert '浙江省博物馆' in reservation_text
    assert '灵隐寺' in reservation_text
    assert '西湖整体门票' not in reservation_text

    assert '地铁' in plan.raw_route['trip_profile']['local_label']
    assert '打车' in plan.raw_route['trip_profile']['local_label']
    for day in plan.daily_itinerary:
        combined_meals = ' '.join(day.meals)
        attraction_names = [item.get('name', '') for item in day.attractions]
        anchors = [day.anchor_city, *attraction_names]
        assert day.meals
        assert day.hotel_hint
        assert any(anchor and anchor in combined_meals for anchor in anchors)
        assert any(anchor and anchor in day.hotel_hint for anchor in anchors)
    for day in destination_days:
        names = [item.get('name', '') for item in day.attractions]
        if len(names) > 2:
            assert all(name in required for name in names)
