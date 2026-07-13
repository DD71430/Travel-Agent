from travel_agent.services.weather_service import build_weather_context, build_weather_plan_summary, build_weather_tips, classify_weather_suitability


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

    def fake_weather_info(adcode):
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

    def fake_weather_info(adcode):
        calls.append(adcode)
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

    assert calls == ['320300', '330100']
    assert [item['city'] for item in context['daily_weather']] == ['徐州', '杭州']
    assert context['daily_weather'][0]['data_source'] == 'tencent_maps'
    assert context['daily_weather'][0]['fallback_reason'] is None
