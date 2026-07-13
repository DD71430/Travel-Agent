from travel_agent.services.route_stop_service import infer_route_stops


def test_infer_route_stops_uses_waypoints_first():
    stops = infer_route_stops(
        origin='济南',
        destination='成都',
        route_days=3,
        waypoints=[{'name': '洛阳'}, {'name': '西安'}],
    )
    assert [item['name'] for item in stops[:2]] == ['洛阳', '西安']
    assert all(item['data_source'] == 'user_waypoint' for item in stops[:2])


def test_infer_route_stops_fallbacks_for_jinan_to_chengdu():
    stops = infer_route_stops(origin='济南', destination='成都', route_days=3)
    names = [item['name'] for item in stops]
    assert len(stops) >= 2
    assert any(name in names for name in ('郑州', '洛阳', '西安', '汉中'))
    assert all(item['data_source'] in {'fallback_city_hint', 'destination_fallback'} for item in stops)


def test_infer_route_stops_preserves_waypoint_details():
    stops = infer_route_stops(
        origin='济南',
        destination='成都',
        route_days=3,
        waypoints=[
            {'name': '西安', 'type': 'city', 'must_visit': True},
            {'name': '龙门石窟', 'type': 'attraction', 'must_visit': True},
        ],
    )
    by_name = {item['name']: item for item in stops}
    assert by_name['西安']['must_visit'] is True
    assert by_name['龙门石窟']['must_visit'] is True
    assert by_name['龙门石窟']['type'] == 'attraction'
    assert 1 <= by_name['龙门石窟']['stage_day'] <= 3
