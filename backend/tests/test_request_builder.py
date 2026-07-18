from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.request_builder import build_travel_request
from travel_agent.services.transport_mode_service import parse_transport_modes


COMPREHENSIVE_TRIP_PROMPT = (
    '帮我规划一个从济南出发到杭州的 5 天 4 晚旅行方案，乘高铁跨城，市内以地铁和打车为主。'
    '途中希望在徐州停留 1 天，顺路去徐州博物馆和云龙湖；'
    '到杭州后玩 3 天，必须安排西湖、浙江省博物馆、灵隐寺和河坊街。'
    '同行有老人和一个小朋友，节奏轻松一点，少走路，不爬山，偏好历史文化、博物馆、经典景点和本地美食。'
    '预算控制在 6000 元左右。请结合未来天气安排每天上午、下午、晚上行程，推荐每天附近餐厅和住宿区域，'
    '并说明交通方式、天气调整、装备建议和哪些景点需要提前预约。'
)


def test_explicit_origin_destination_win():
    request = ChatRequest(question='三天两晚预算3000', origin='济南', destination='北京')
    travel_request = build_travel_request(request)
    assert travel_request.origin == '济南'
    assert travel_request.destination == '北京'


def test_parse_origin_destination_from_question():
    request = ChatRequest(question='从济南到北京三天两晚预算3000')
    travel_request = build_travel_request(request)
    assert travel_request.origin == '济南'
    assert travel_request.destination == '北京'


def test_budget_text_is_not_exposed_as_planning_capability():
    request = ChatRequest(question='从济南到北京三天两晚预算3000')
    travel_request = build_travel_request(request)
    assert '预算：' not in (travel_request.preferences or '')
    assert travel_request.trip_profile.get('budget') is None


def test_travel_mode_detection():
    assert build_travel_request(ChatRequest(question='从济南到北京公交')).travel_mode == 'transit'
    assert build_travel_request(ChatRequest(question='从济南到北京步行')).travel_mode == 'walking'
    assert build_travel_request(ChatRequest(question='从济南到北京骑行')).travel_mode == 'bicycling'
    assert build_travel_request(ChatRequest(question='从济南到北京自驾')).travel_mode == 'driving'


def test_high_speed_rail_is_structured_separately_from_local_mode():
    result = build_travel_request(
        ChatRequest(question='帮我规划一个从济南到杭州三天两晚的旅行路线，要求乘坐高铁，在徐州游玩一天，剩余时间在杭州游玩')
    )

    assert result.travel_mode == 'transit'
    assert result.trip_profile['intercity_mode'] == 'high_speed_rail'
    assert result.trip_profile['local_mode'] == 'mixed'
    assert result.trip_profile['transport_preference_source'] == 'question'


def test_city_transport_keeps_metro_and_taxi_preference():
    modes = parse_transport_modes('市内以地铁和打车为主', fallback_travel_mode='transit')
    assert modes['local_mode'] == 'mixed'
    assert '地铁' in modes['local_label']
    assert '打车' in modes['local_label']

    result = build_travel_request(ChatRequest(question=COMPREHENSIVE_TRIP_PROMPT))
    assert result.trip_profile['local_mode'] == 'mixed'
    assert '地铁' in result.trip_profile['local_label']
    assert '打车' in result.trip_profile['local_label']


def test_waypoints_json_parsing():
    request = ChatRequest(question='从济南到北京途经泰安', waypoints_json='[{"name":"曲阜"}]')
    travel_request = build_travel_request(request)
    assert [item.name for item in travel_request.waypoints] == ['曲阜', '泰安']


def test_request_builder_carries_parsed_waypoints_and_must_visit():
    request = ChatRequest(question='从济南自驾到成都，途经西安和汉中，沿途必须去龙门石窟，按我输入的顺序走')
    result = build_travel_request(request)
    waypoint_names = [waypoint.name for waypoint in result.waypoints]
    assert '西安' in waypoint_names
    assert '汉中' in waypoint_names
    assert '龙门石窟' in waypoint_names
    assert '龙门石窟' in result.trip_profile['must_visit_attractions']
    assert result.trip_profile['waypoint_order_mode'] == 'user_order'
    assert result.waypoint_order is False


def test_request_builder_cleans_stopover_connector_before_action():
    result = build_travel_request(
        ChatRequest(question='帮我规划一个从杭州到济南三天两晚的旅行路线，乘坐高铁，途经徐州并停留一天，偏好经典景点和合理游览节奏')
    )
    waypoint_names = [waypoint.name for waypoint in result.waypoints]
    route_stop_names = [stop['name'] for stop in result.trip_profile['route_stops']]

    assert result.origin == '杭州'
    assert result.destination == '济南'
    assert route_stop_names == ['徐州']
    assert set(waypoint_names).issubset({'徐州'})
    assert '徐州并停留一天' not in waypoint_names
    assert '徐州并停留' not in waypoint_names
    assert not any(name.startswith('途经徐州并') or name == '徐州并' for name in waypoint_names + route_stop_names)


def test_request_builder_extracts_destination_must_visit_list():
    result = build_travel_request(ChatRequest(question=COMPREHENSIVE_TRIP_PROMPT))
    must_visits = set(result.trip_profile['must_visit_attractions'])
    assert {'西湖', '浙江省博物馆', '灵隐寺', '河坊街'}.issubset(must_visits)
