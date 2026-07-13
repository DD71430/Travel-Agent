from travel_agent.services.poi_candidate_service import fetch_route_poi_candidates


def test_plain_waypoint_candidate_is_not_must_visit():
    candidates = fetch_route_poi_candidates(
        [{'name': '曲阜', 'type': 'city', 'must_visit': False, 'stage_day': 1}],
        {'interest_tags': ['历史文化']},
        {},
    )
    waypoint = next(item for item in candidates if item['name'] == '曲阜')
    assert waypoint['source'] == 'user_waypoint'
    assert waypoint['must_visit'] is False


def test_explicit_must_visit_candidate_keeps_priority():
    candidates = fetch_route_poi_candidates(
        [{'name': '龙门石窟', 'type': 'attraction', 'must_visit': True, 'stage_day': 1}],
        {'interest_tags': ['历史文化']},
        {},
    )
    assert candidates[0]['name'] == '龙门石窟'
    assert candidates[0]['must_visit'] is True
    assert candidates[0]['source'] == 'user_required'


def test_attraction_poi_filter_rejects_food_hotel_and_shop_like_pois():
    from travel_agent.services.poi_candidate_service import is_valid_attraction_poi

    assert not is_valid_attraction_poi({'name': '星巴克(杭州建德严州古城店)', 'category': '咖啡店', 'address': '杭州市建德市'})
    assert not is_valid_attraction_poi({'name': '杭州西湖国宾馆', 'category': '酒店', 'address': '杭州市西湖区'})
    assert not is_valid_attraction_poi({'name': '杭州本地特色餐厅', 'category': '餐厅', 'address': '杭州市上城区'})
    assert is_valid_attraction_poi({'name': '杭州博物馆', 'category': '博物馆', 'address': '杭州市上城区'})
    assert is_valid_attraction_poi({'name': '小河直街历史文化街区', 'category': '旅游景点;历史文化街区', 'address': '杭州市拱墅区'})


def test_destination_scope_excludes_hangzhou_far_suburbs_unless_explicit():
    from travel_agent.services.poi_candidate_service import is_poi_in_planning_scope

    jiande_poi = {'name': '严州古城', 'category': '古城', 'address': '杭州市建德市梅城镇'}
    assert not is_poi_in_planning_scope(jiande_poi, '杭州', {'stage': 'destination'}, {'must_visit_attractions': []})
    assert is_poi_in_planning_scope(
        jiande_poi,
        '杭州',
        {'stage': 'destination'},
        {'must_visit_attractions': ['建德严州古城'], 'source_text': '想去建德严州古城'},
    )


def test_route_anchor_scope_rejects_destination_city_pois():
    from travel_agent.services.poi_candidate_service import is_poi_in_planning_scope

    hangzhou_poi = {'name': '西湖风景名胜区', 'category': '景区', 'address': '杭州市西湖区'}
    assert not is_poi_in_planning_scope(hangzhou_poi, '徐州', {'stage': 'route'}, {'route_stops': [{'name': '徐州'}]})
