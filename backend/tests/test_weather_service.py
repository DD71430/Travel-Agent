from travel_agent.services.weather_service import build_weather_context, classify_weather_suitability


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


def test_build_weather_context_fallback_without_adcode(monkeypatch):
    from travel_agent.services import weather_service

    monkeypatch.setattr(weather_service.settings, 'tencent_maps_key', 'fake-key')
    context = build_weather_context('南京', days=1, location_debug={})
    assert context['data_source'] == 'fallback'
    assert context['request_debug']['fallback_reason'] == 'missing_key_or_weather_unavailable'
