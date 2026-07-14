from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.request_builder import build_travel_request


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
