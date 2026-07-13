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


def test_parse_route_and_destination_stage_days():
    profile = build_trip_profile_from_text('从济南自驾到成都，途中游玩三天，到成都游玩四天，喜欢博物馆和公园')
    assert profile['route_days'] == 3
    assert profile['destination_days'] == 4
    assert profile['duration_days'] == 7
    assert profile['stage_plan_mode'] == 'route_then_destination'
    assert profile['trip_type'] == 'along_route_trip'
    assert '博物馆' in profile['interest_tags']
    assert '公园' in profile['interest_tags']


def test_parse_stopover_day_and_destination_remainder():
    question = '从济南自驾到杭州三天两晚，在徐州停留一天，剩余时间在杭州游玩，优先经典景点和合理游览节奏'

    request = build_travel_request(ChatRequest(question=question))
    profile = build_trip_profile(request)

    assert request.origin == '济南'
    assert request.destination == '杭州'
    assert request.travel_mode == 'driving'
    assert any(stop['name'] == '徐州' for stop in profile['route_stops'])
    assert profile['route_days'] >= 1
    assert profile['destination_days'] >= 1
    assert profile['destination_stay_days'] == profile['destination_days']


def test_parse_stage_sum_when_route_and_destination_days_are_explicit():
    profile = build_trip_profile_from_text('从济南到成都，途中游玩三天，到成都游玩三天')

    assert profile['route_days'] == 3
    assert profile['destination_days'] == 3
    assert profile['duration_days'] == 6


def test_parse_destination_only_when_route_has_no_play():
    profile = build_trip_profile_from_text('从北京到西安，中途不玩，到西安玩三天')
    assert profile['route_days'] == 0
    assert profile['destination_days'] == 3
    assert profile['duration_days'] == 3
    assert profile['stage_plan_mode'] == 'destination_only'


def test_parse_route_only_when_destination_has_no_play():
    profile = build_trip_profile_from_text('从杭州自驾到南京，沿途安排两天，目的地不玩')
    assert profile['route_days'] == 2
    assert profile['destination_days'] == 0
    assert profile['duration_days'] == 2
    assert profile['stage_plan_mode'] == 'route_only'


def test_score_poi_prefers_route_order_during_route_stage():
    profile = {'interest_tags': ['公园'], 'avoid_tags': [], 'pace': 'normal'}
    on_route = score_poi({'name': '沿途湿地公园', 'category': '公园', 'route_order': 1}, profile, {'stage': 'route', 'daily_available_visit_minutes': 180})
    off_route = score_poi({'name': '目的地湿地公园', 'category': '公园'}, profile, {'stage': 'route', 'daily_available_visit_minutes': 180})
    assert on_route['final_score'] > off_route['final_score']


def test_score_poi_destination_stage_prefers_preference_match():
    profile = {'interest_tags': ['博物馆'], 'avoid_tags': [], 'pace': 'normal'}
    museum = score_poi({'name': '成都博物馆', 'category': '博物馆'}, profile, {'stage': 'destination', 'daily_available_visit_minutes': 300})
    mall = score_poi({'name': '成都购物中心', 'category': '商场'}, profile, {'stage': 'destination', 'daily_available_visit_minutes': 300})
    assert museum['final_score'] > mall['final_score']


def test_score_poi_rainy_weather_prefers_indoor():
    profile = {'interest_tags': ['博物馆', '公园'], 'avoid_tags': [], 'pace': 'normal'}
    weather_day = {'indoor_priority': True, 'outdoor_suitability': 'limited', 'weather': '阵雨'}
    museum = score_poi({'name': '成都博物馆', 'category': '博物馆'}, profile, {'stage': 'destination', 'weather_day': weather_day})
    park = score_poi({'name': '人民公园', 'category': '公园'}, profile, {'stage': 'destination', 'weather_day': weather_day})
    assert museum['final_score'] > park['final_score']
    assert '天气适配' in str(museum['reason'])


def test_score_poi_sunny_weather_does_not_penalize_park():
    profile = {'interest_tags': ['公园'], 'avoid_tags': [], 'pace': 'normal'}
    weather_day = {'indoor_priority': False, 'outdoor_suitability': 'good', 'weather': '晴'}
    park = score_poi({'name': '人民公园', 'category': '公园'}, profile, {'stage': 'destination', 'weather_day': weather_day})
    museum = score_poi({'name': '成都博物馆', 'category': '博物馆'}, profile, {'stage': 'destination', 'weather_day': weather_day})
    assert park['final_score'] >= museum['final_score']


def test_score_poi_storm_penalizes_mountain_walk():
    profile = {'interest_tags': ['自然风光'], 'avoid_tags': [], 'pace': 'normal'}
    weather_day = {'indoor_priority': True, 'outdoor_suitability': 'poor', 'weather': '暴雨'}
    mountain = score_poi({'name': '青城山步道', 'category': '山岳徒步'}, profile, {'stage': 'destination', 'weather_day': weather_day})
    museum = score_poi({'name': '成都博物馆', 'category': '博物馆'}, profile, {'stage': 'destination', 'weather_day': weather_day})
    assert mountain['final_score'] < museum['final_score']


def test_score_poi_must_visit_gets_priority():
    profile = {'interest_tags': [], 'avoid_tags': [], 'pace': 'normal'}
    required = score_poi({'name': '龙门石窟', 'category': '历史文化', 'must_visit': True}, profile, {'stage': 'route'})
    normal = score_poi({'name': '普通景点', 'category': '历史文化'}, profile, {'stage': 'route'})
    assert required['final_score'] > normal['final_score']
    assert '用户指定必去' in str(required['reason'])


def test_score_poi_keeps_must_visit_outdoor_during_storm_with_warning():
    profile = {'interest_tags': [], 'avoid_tags': [], 'pace': 'normal'}
    weather_day = {'indoor_priority': True, 'outdoor_suitability': 'poor', 'weather': '暴雨'}
    required = score_poi({'name': '青城山步道', 'category': '山岳徒步', 'must_visit': True}, profile, {'stage': 'route', 'weather_day': weather_day})
    normal = score_poi({'name': '青城山步道', 'category': '山岳徒步'}, profile, {'stage': 'route', 'weather_day': weather_day})
    assert required['final_score'] > normal['final_score']
    assert '建议视天气调整' in str(required['reason'])
