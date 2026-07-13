from travel_agent.services.waypoint_service import extract_must_visit_attractions, extract_waypoint_details, extract_waypoint_order_mode


def test_extract_waypoint_details_keeps_order():
    details = extract_waypoint_details('从济南自驾到成都，途经西安和汉中')
    assert [item['name'] for item in details[:2]] == ['西安', '汉中']
    assert all(item['type'] != '' for item in details[:2])


def test_extract_must_visit_and_waypoint_details():
    text = '沿途必须去洛阳龙门石窟，不要遗漏陕西历史博物馆'
    must_visit = extract_must_visit_attractions(text)
    details = extract_waypoint_details(text)
    assert '洛阳龙门石窟' in must_visit
    assert '陕西历史博物馆' in must_visit
    required = {item['name']: item for item in details}
    assert required['洛阳龙门石窟']['must_visit'] is True
    assert required['陕西历史博物馆']['must_visit'] is True


def test_extract_waypoint_order_mode_optimize():
    assert extract_waypoint_order_mode('帮我优化途经点顺序') == 'optimize'


def test_extract_waypoint_order_mode_user_order():
    assert extract_waypoint_order_mode('按我输入的顺序走') == 'user_order'
