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


def test_waypoints_json_parsing():
    request = ChatRequest(question='从济南到北京途经泰安', waypoints_json='[{"name":"曲阜"}]')
    travel_request = build_travel_request(request)
    assert [item.name for item in travel_request.waypoints] == ['曲阜', '泰安']
