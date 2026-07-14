from travel_agent.services.intent_service import classify_chat_intent, extract_locations, extract_trip_details


def test_general_chat_intent():
    assert classify_chat_intent('你好你是谁') == 'general_chat'


def test_travel_planning_intent():
    assert classify_chat_intent('从济南到北京三天两晚预算3000') == 'travel_planning'


def test_nearby_search_intent():
    assert classify_chat_intent('故宫附近酒店餐厅景点') == 'nearby_search'


def test_weather_query_intent():
    assert classify_chat_intent('杭州天气怎么样') == 'weather_query'
    assert classify_chat_intent('查一下徐州天气') == 'weather_query'
    assert classify_chat_intent('腾讯天气接通了吗') == 'weather_query'


def test_weather_word_in_travel_plan_stays_travel_planning():
    assert classify_chat_intent('从济南到杭州三天两晚，考虑天气') == 'travel_planning'


def test_travel_plan_with_recommend_attractions_is_not_nearby():
    assert classify_chat_intent('帮我规划一个从杭州到西安三天两晚的旅行路线，优先经典景点和合理游览节奏') == 'travel_planning'


def test_extract_chinese_duration():
    details = extract_trip_details('从济南到北京三天两晚预算3000')
    assert details['duration_days'] == '3'
    assert details['nights'] == '2'


def test_extract_locations():
    assert extract_locations('从济南到北京三天两晚预算3000') == ('济南', '北京')
