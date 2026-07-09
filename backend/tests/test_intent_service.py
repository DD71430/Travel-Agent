from travel_agent.services.intent_service import classify_chat_intent, extract_locations, extract_trip_details


def test_general_chat_intent():
    assert classify_chat_intent('你好你是谁') == 'general_chat'


def test_travel_planning_intent():
    assert classify_chat_intent('从济南到北京三天两晚预算3000') == 'travel_planning'


def test_nearby_search_intent():
    assert classify_chat_intent('故宫附近酒店餐厅景点') == 'nearby_search'


def test_extract_chinese_duration():
    details = extract_trip_details('从济南到北京三天两晚预算3000')
    assert details['duration_days'] == '3'
    assert details['nights'] == '2'


def test_extract_locations():
    assert extract_locations('从济南到北京三天两晚预算3000') == ('济南', '北京')
