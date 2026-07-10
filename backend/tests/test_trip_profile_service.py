from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.request_builder import build_travel_request
from travel_agent.services.trip_profile_service import build_trip_profile, build_trip_profile_from_text, score_poi


def test_parse_along_route_trip_profile():
    profile = build_trip_profile_from_text('从济南自驾到南京三天两晚，沿途想看博物馆和公园')
    assert profile['trip_type'] == 'along_route_trip'
    assert profile['travel_mode'] == 'driving'
    assert profile['duration_days'] == 3
    assert '博物馆' in profile['interest_tags']
    assert '公园' in profile['interest_tags']


def test_request_builder_carries_profile_tags():
    request = build_travel_request(ChatRequest(question='从济南自驾到南京三天两晚，沿途想看博物馆和公园'))
    profile = build_trip_profile(request)
    assert profile['trip_type'] == 'along_route_trip'
    assert '博物馆' in profile['interest_tags']


def test_score_poi_prefers_museum_over_mall():
    profile = {'interest_tags': ['博物馆'], 'avoid_tags': [], 'pace': 'normal'}
    museum = score_poi({'name': '南京博物院', 'category': '博物馆'}, profile, {'daily_available_visit_minutes': 240})
    mall = score_poi({'name': '某购物中心', 'category': '商场'}, profile, {'daily_available_visit_minutes': 240})
    assert museum['final_score'] > mall['final_score']


def test_score_poi_penalizes_mountain_when_avoiding_climb():
    profile = {'interest_tags': ['自然风光'], 'avoid_tags': ['不爬山'], 'pace': 'relaxed'}
    mountain = score_poi({'name': '紫金山登山步道', 'category': '山岳徒步'}, profile, {'daily_available_visit_minutes': 180})
    park = score_poi({'name': '玄武湖公园', 'category': '公园'}, profile, {'daily_available_visit_minutes': 180})
    assert mountain['final_score'] < park['final_score']
