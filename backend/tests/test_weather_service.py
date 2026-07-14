from datetime import date, timedelta

from travel_agent.services.weather_service import build_weather_context, build_weather_plan_summary, build_weather_tips, classify_weather_suitability, extract_tencent_weather_days


def test_classify_rain_prioritizes_indoor():
    result = classify_weather_suitability('阵雨')
    assert result['indoor_priority'] is True
    assert result['outdoor_suitability'] == 'limited'


def test_classify_extreme_weather_as_high_risk():
    result = classify_weather_suitability('暴雨')
    assert result['risk_level'] == 'high'
    assert result['outdoor_suitability'] == 'poor'


def test_classify_sunny_weather_as_outdoor_good():
    result = classify_weather_suitability('晴')
    assert result['outdoor_suitability'] == 'good'
    assert result['indoor_priority'] is False


def test_classify_high_temperature_avoids_midday_outdoor():
    result = classify_weather_suitability('晴', '36℃')
    assert result['indoor_priority'] is True
    assert '中午避免室外' in result['strategy']


def test_classify_freezing_temperature_prioritizes_indoor():
    result = classify_weather_suitability('多云', '-2℃')
    assert result['indoor_priority'] is True
    assert result['outdoor_suitability'] == 'limited'


def test_build_weather_context_fallback_without_key(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', '')
    context = build_weather_context('成都', days=3)
    assert context['data_source'] == 'fallback'
    assert len(context['daily_weather']) == 3
    assert context['summary']
    assert 'weather_unconfirmed' in context['daily_weather'][0]['weather_tags']
    assert any('天气待确认' in tip for tip in context['daily_weather'][0]['weather_tips'])


def test_build_weather_context_uses_tencent_when_adcode_exists(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')

    def fake_weather_info(adcode, weather_type=None):
        assert adcode == '320100'
        return {
            'status': 0,
            'result': {
                'forecast': [
                    {'weather': '阵雨', 'min_temperature': '22', 'max_temperature': '28', 'wind_direction': '东风'},
                ]
            },
        }

    monkeypatch.setattr(weather_service._client, 'weather_info', fake_weather_info)
    context = build_weather_context('南京', days=1, location_debug={'destination_adcode': '320100'})
    assert context['data_source'] == 'tencent_maps'
    assert context['daily_weather'][0]['indoor_priority'] is True
    assert 'rain' in context['daily_weather'][0]['weather_tags']
    assert any('雨伞' in tip or '雨衣' in tip for tip in context['daily_weather'][0]['weather_tips'])


def test_build_weather_context_accepts_tencent_realtime_payload(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')

    def fake_weather_info(adcode, weather_type=None):
        assert adcode == '330100'
        return {
            'status': 0,
            'message': 'Success',
            'result': {
                'realtime': [
                    {
                        'adcode': adcode,
                        'city': '杭州市',
                        'infos': {
                            'weather': '晴天',
                            'temperature': 36,
                            'wind_direction': '西南风',
                            'wind_power': '3-4级',
                        },
                    }
                ]
            },
        }

    monkeypatch.setattr(weather_service._client, 'weather_info', fake_weather_info)

    context = build_weather_context('杭州', days=1, location_debug={'destination_adcode': '330100'})

    assert context['data_source'] == 'tencent_maps'
    assert context['daily_weather'][0]['data_source'] == 'tencent_maps'
    assert context['daily_weather'][0]['weather'] == '晴天'
    assert context['daily_weather'][0]['temperature'] == '36℃'
    assert 'heat' in context['daily_weather'][0]['weather_tags']
    assert any('防晒' in tip or '补水' in tip for tip in context['daily_weather'][0]['weather_tips'])


def test_build_weather_context_accepts_tencent_future_infos_payload(monkeypatch):
    from travel_agent.services import weather_service

    calls = []
    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')

    def fake_weather_info(adcode, weather_type=None):
        calls.append((adcode, weather_type))
        return {
            'status': 0,
            'message': 'Success',
            'result': {
                'forecast': [
                    {
                        'adcode': adcode,
                        'city': '徐州市',
                        'infos': [
                            {'date': '2026-07-14', 'day': {'weather': '晴天', 'temperature': 34, 'wind_direction': '西风'}, 'night': {'weather': '小雨', 'temperature': 26, 'wind_direction': '北风'}},
                            {'date': '2026-07-15', 'day': {'weather': '中雨', 'temperature': 33, 'wind_direction': '东风'}, 'night': {'weather': '大雨', 'temperature': 25, 'wind_direction': '北风'}},
                            {'date': '2026-07-16', 'day': {'weather': '多云', 'temperature': 32, 'wind_direction': '北风'}, 'night': {'weather': '晴天', 'temperature': 24, 'wind_direction': '北风'}},
                        ],
                    }
                ]
            },
        }

    monkeypatch.setattr(weather_service._client, 'weather_info', fake_weather_info)

    context = build_weather_context('徐州', days=3, location_debug={'destination_adcode': '320300'})

    assert calls == [('320300', 'future')]
    assert context['data_source'] == 'tencent_maps'
    assert len(context['daily_weather']) == 3
    assert [item['weather'] for item in context['daily_weather']] == ['晴天转小雨', '中雨转大雨', '多云转晴天']
    assert context['daily_weather'][0]['temperature'] == '26-34℃'
    assert 'rain' in context['daily_weather'][1]['weather_tags']


def test_weather_extraction_prefers_payload_date_over_array_order():
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    payload = {
        'status': 0,
        'result': {
            'forecast': [
                {'date': tomorrow, 'weather': '明日天气', 'min_temperature': '21', 'max_temperature': '29'},
                {'date': today, 'weather': '今日天气', 'min_temperature': '20', 'max_temperature': '28'},
            ]
        },
    }

    daily = extract_tencent_weather_days(payload, '徐州', 2)

    assert [item['weather'] for item in daily] == ['今日天气', '明日天气']
    assert [item['forecast_date'] for item in daily] == [today, tomorrow]
    assert [item['forecast_index'] for item in daily] == [1, 0]


def test_build_weather_tips_for_tencent_rain():
    result = build_weather_tips({'weather': '阵雨', 'temperature': '22-28℃'}, data_source='tencent_maps')

    assert 'rain' in result['weather_tags']
    assert any('雨伞' in tip or '雨衣' in tip for tip in result['weather_tips'])
    assert '雨伞或轻便雨衣' in result['packing_tips']


def test_build_weather_tips_for_tencent_heat_and_sun():
    result = build_weather_tips({'weather': '晴', 'temperature': '30-36℃'}, data_source='tencent_maps')

    assert 'sun_exposure' in result['weather_tags']
    assert 'heat' in result['weather_tags']
    assert any('防晒' in tip or '补水' in tip for tip in result['weather_tips'])
    assert any('避开正午户外暴晒' in tip for tip in result['weather_tips'])
    assert '防晒霜' in result['packing_tips']
    assert '水杯' in result['packing_tips']


def test_build_weather_tips_for_fallback_are_honest():
    result = build_weather_tips({'weather': '阵雨', 'temperature': '36℃'}, data_source='fallback')

    combined = ' '.join([*result['weather_tags'], *result['weather_tips'], *result['packing_tips']])
    assert 'weather_unconfirmed' in result['weather_tags']
    assert '天气待确认' in combined
    assert '保留雨具、防晒和补水用品作为备选' in combined
    assert '今天下雨' not in combined
    assert '今天高温' not in combined


def test_build_weather_context_fallback_without_adcode(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')
    context = build_weather_context('南京', days=1, location_debug={})
    assert context['data_source'] == 'fallback'
    assert context['request_debug']['fallback_reason'] == 'missing_key_or_weather_unavailable'


def test_weather_plan_summary_for_rain_makes_adjustments_visible():
    summary = build_weather_plan_summary(
        {
            'data_source': 'tencent_maps',
            'daily_weather': [
                {
                    'day': 1,
                    'city': '杭州',
                    'weather': '阵雨',
                    'temperature': '22-28℃',
                    'indoor_priority': True,
                    'outdoor_suitability': 'limited',
                    'weather_tips': ['有降雨风险，建议携带雨伞或轻便雨衣。'],
                    'packing_tips': ['雨伞或轻便雨衣', '防滑鞋'],
                }
            ],
        },
        [],
    )

    combined = ' '.join([summary['weather_overview'], *summary['daily_weather_briefs'], *summary['weather_adjustments'], *summary['packing_summary']])
    assert '带伞' in combined or '雨衣' in combined
    assert '防滑' in combined
    assert any('室内' in item or '遮蔽' in item for item in summary['weather_adjustments'])


def test_weather_plan_summary_for_fallback_stays_optional():
    summary = build_weather_plan_summary(
        {
            'data_source': 'fallback',
            'daily_weather': [
                {'day': 1, 'city': '杭州', 'weather': '阵雨', 'temperature': '36℃'},
            ],
        },
        [],
    )

    combined = ' '.join([summary['weather_overview'], *summary['daily_weather_briefs'], *summary['weather_adjustments'], *summary['packing_summary']])
    assert '天气待确认' in combined
    assert '雨具、防晒和补水用品作为备选' in combined
    assert '今天下雨' not in combined
    assert '今天高温' not in combined
    assert '雨天优先室内' not in combined


def test_weather_context_uses_route_stop_adcodes_per_day(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')
    calls = []

    def fake_weather_info(adcode, weather_type=None):
        calls.append((adcode, weather_type))
        weather = '阵雨' if adcode == '320300' else '晴'
        return {
            'status': 0,
            'result': {
                'forecast': [
                    {'weather': weather, 'min_temperature': '22', 'max_temperature': '31', 'wind_direction': '东风'},
                ]
            },
        }

    monkeypatch.setattr(weather_service._client, 'weather_info', fake_weather_info)

    context = build_weather_context(
        '杭州',
        route_stops=[{'name': '徐州', 'adcode': '320300'}, {'name': '杭州', 'adcode': '330100'}],
        days=2,
        location_debug={'destination_adcode': '330100'},
    )

    assert calls == [('320300', 'future'), ('330100', 'future')]
    assert [item['city'] for item in context['daily_weather']] == ['徐州', '杭州']
    assert context['daily_weather'][0]['data_source'] == 'tencent_maps'
    assert context['daily_weather'][0]['fallback_reason'] is None


def test_weather_context_uses_daily_anchor_cities_for_segmented_trip(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')
    calls = []

    def fake_weather_info(adcode, weather_type=None):
        calls.append((adcode, weather_type))
        forecasts = {
            '320300': [
                {'weather': '阵雨', 'min_temperature': '25', 'max_temperature': '33', 'wind_direction': '东风'},
            ],
            '330100': [
                {'weather': '多云', 'min_temperature': '28', 'max_temperature': '37', 'wind_direction': '南风'},
                {'weather': '晴', 'min_temperature': '29', 'max_temperature': '38', 'wind_direction': '南风'},
                {'weather': '晴转多云', 'min_temperature': '27', 'max_temperature': '36', 'wind_direction': '南风'},
            ],
        }
        return {'status': 0, 'result': {'forecast': forecasts[adcode]}}

    monkeypatch.setattr(weather_service._client, 'weather_info', fake_weather_info)

    context = build_weather_context(
        '杭州',
        days=3,
        location_debug={'destination_adcode': '330100'},
        daily_plan_context=[
            {'day': 1, 'anchor_city': '徐州'},
            {'day': 2, 'anchor_city': '杭州'},
            {'day': 3, 'anchor_city': '杭州'},
        ],
    )

    assert calls == [('320300', 'future'), ('330100', 'future')]
    assert [item['city'] for item in context['daily_weather']] == ['徐州', '杭州', '杭州']
    targets = context['request_debug']['weather_targets']
    assert [item['city'] for item in targets] == ['徐州', '杭州', '杭州']
    assert [item['adcode'] for item in targets] == ['320300', '330100', '330100']
    assert all(item['data_source'] == 'tencent_maps' for item in targets)


def test_weather_context_geocodes_unknown_daily_anchor_city(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')
    geocoder_calls = []

    def fake_geocoder(address, region=None):
        geocoder_calls.append((address, region))
        return {'status': 0, 'result': {'ad_info': {'adcode': '370400'}, 'location': {'lat': 34.81, 'lng': 117.32}}}

    def fake_weather_info(adcode, weather_type=None):
        assert adcode == '370400'
        assert weather_type == 'future'
        return {
            'status': 0,
            'result': {
                'forecast': [
                    {'weather': '小雨转多云', 'min_temperature': '24', 'max_temperature': '31', 'wind_direction': '东风'},
                ]
            },
        }

    monkeypatch.setattr(weather_service._client, 'geocoder', fake_geocoder)
    monkeypatch.setattr(weather_service._client, 'weather_info', fake_weather_info)

    context = build_weather_context(
        '西安',
        days=1,
        location_debug={},
        daily_plan_context=[{'day': 1, 'anchor_city': '枣庄'}],
    )

    assert geocoder_calls == [('枣庄', '枣庄')]
    assert context['daily_weather'][0]['city'] == '枣庄'
    assert context['daily_weather'][0]['adcode'] == '370400'
    assert context['daily_weather'][0]['data_source'] == 'tencent_maps'
    assert context['request_debug']['weather_targets'][0]['adcode_source'] == 'geocoder'


def test_weather_context_retries_realtime_when_future_forecast_is_empty(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')
    calls = []

    def fake_weather_info(adcode, weather_type=None):
        calls.append((adcode, weather_type))
        if adcode == '320300' and weather_type == 'future':
            return {'status': 0, 'result': {'forecast': []}}
        if adcode == '320300':
            return {
                'status': 0,
                'result': {
                    'realtime': [
                        {
                            'adcode': adcode,
                            'city': '徐州市',
                            'infos': {'weather': '晴天', 'temperature': 34, 'wind_direction': '西风', 'wind_power': '3级'},
                        }
                    ]
                },
            }
        return {
            'status': 0,
            'result': {
                'forecast': [
                    {'weather': '多云', 'min_temperature': '28', 'max_temperature': '37', 'wind_direction': '南风'},
                    {'weather': '晴', 'min_temperature': '29', 'max_temperature': '38', 'wind_direction': '南风'},
                ]
            },
        }

    monkeypatch.setattr(weather_service._client, 'weather_info', fake_weather_info)

    context = build_weather_context(
        '杭州',
        days=2,
        location_debug={},
        daily_plan_context=[{'day': 1, 'anchor_city': '徐州'}, {'day': 2, 'anchor_city': '杭州'}],
    )

    assert calls == [('320300', 'future'), ('320300', None), ('330100', 'future')]
    assert context['data_source'] == 'tencent_maps'
    assert context['daily_weather'][0]['city'] == '徐州'
    assert context['daily_weather'][0]['data_source'] == 'tencent_maps'
    assert context['daily_weather'][0]['fallback_reason'] is None
    assert context['daily_weather'][0]['weather'] == '晴天'
    assert context['daily_weather'][1]['city'] == '杭州'


def test_segmented_weather_uses_absolute_forecast_day_for_each_city(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')

    def fake_weather_info(adcode, weather_type=None):
        assert weather_type == 'future'
        prefix = '徐' if adcode == '320300' else '济'
        return {
            'status': 0,
            'result': {
                'forecast': [
                    {'weather': f'{prefix}州预报0', 'min_temperature': '20', 'max_temperature': '28'},
                    {'weather': f'{prefix}州预报1', 'min_temperature': '21', 'max_temperature': '29'},
                    {'weather': f'{prefix}州预报2', 'min_temperature': '22', 'max_temperature': '30'},
                ]
            },
        }

    monkeypatch.setattr(weather_service._client, 'weather_info', fake_weather_info)

    context = build_weather_context(
        '济南',
        days=3,
        location_debug={'destination_adcode': '370100'},
        daily_plan_context=[
            {'day': 1, 'anchor_city': '徐州'},
            {'day': 2, 'anchor_city': '徐州'},
            {'day': 3, 'anchor_city': '济南'},
        ],
    )

    assert [item['weather'] for item in context['daily_weather']] == ['徐州预报0', '徐州预报1', '济州预报2']
    assert [item['day'] for item in context['daily_weather']] == [1, 2, 3]
    assert [item['forecast_index'] for item in context['request_debug']['weather_targets']] == [0, 1, 2]


def test_future_trip_day_does_not_use_realtime_as_forecast(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')
    calls = []

    def fake_weather_info(adcode, weather_type=None):
        calls.append((adcode, weather_type))
        if adcode == '320300':
            return {'status': 0, 'result': {'forecast': [{'weather': '多云', 'min_temperature': '20', 'max_temperature': '28'}]}}
        if weather_type == 'future':
            return {'status': 0, 'result': {'forecast': []}}
        return {
            'status': 0,
            'result': {'realtime': [{'infos': {'weather': '晴', 'temperature': 30}}]},
        }

    monkeypatch.setattr(weather_service._client, 'weather_info', fake_weather_info)

    context = build_weather_context(
        '济南',
        days=2,
        location_debug={'destination_adcode': '370100'},
        daily_plan_context=[
            {'day': 1, 'anchor_city': '徐州'},
            {'day': 2, 'anchor_city': '济南'},
        ],
    )

    assert calls == [('320300', 'future'), ('370100', 'future')]
    assert context['daily_weather'][1]['day'] == 2
    assert context['daily_weather'][1]['city'] == '济南'
    assert context['daily_weather'][1]['data_source'] == 'fallback'
