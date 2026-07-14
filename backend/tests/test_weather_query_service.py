import pytest

from travel_agent.schemas.chat import ChatRequest


def test_weather_query_success_reports_tencent_connected_for_rain(monkeypatch):
    from travel_agent.services import weather_query_service

    monkeypatch.setattr(weather_query_service.settings, 'tencent_maps_key', 'fake-key')
    monkeypatch.setattr(
        weather_query_service._client,
        'geocoder',
        lambda city, region=None: {'result': {'location': {'lat': 30.2741, 'lng': 120.1551}, 'ad_info': {'adcode': '330100'}}},
    )
    monkeypatch.setattr(
        weather_query_service._client,
        'reverse_geocoder',
        lambda location: {'result': {'ad_info': {'adcode': '330100', 'name': '杭州'}}},
    )
    monkeypatch.setattr(
        weather_query_service._client,
        'weather_info',
        lambda adcode, weather_type=None: {
            'result': {
                'forecast': [
                    {'weather': '阵雨', 'min_temperature': '22', 'max_temperature': '28', 'wind_direction': '东风'},
                ]
            }
        },
    )

    response = weather_query_service.build_weather_query_response(ChatRequest(question='杭州天气怎么样', conversation_id='weather-rain'))

    weather = response['data']['weather']
    assert response['answer_type'] == 'weather_query'
    assert weather['connected'] is True
    assert weather['data_source'] == 'tencent_maps'
    assert weather['adcode'] == '330100'
    combined = f"{response['final_answer']} {' '.join(weather['weather_tips'])}"
    assert '腾讯天气已接通' in combined
    assert '雨伞' in combined or '雨衣' in combined
    assert '防滑' in combined
    assert '室内' in combined or '遮蔽' in combined


def test_weather_query_success_reports_heat_advice(monkeypatch):
    from travel_agent.services import weather_query_service

    monkeypatch.setattr(weather_query_service.settings, 'tencent_maps_key', 'fake-key')
    monkeypatch.setattr(
        weather_query_service._client,
        'geocoder',
        lambda city, region=None: {'result': {'location': {'lat': 30.2741, 'lng': 120.1551}, 'ad_info': {'adcode': '330100'}}},
    )
    monkeypatch.setattr(
        weather_query_service._client,
        'reverse_geocoder',
        lambda location: {'result': {'ad_info': {'adcode': '330100', 'name': '杭州'}}},
    )
    monkeypatch.setattr(
        weather_query_service._client,
        'weather_info',
        lambda adcode, weather_type=None: {
            'result': {
                'forecast': [
                    {'weather': '晴', 'min_temperature': '30', 'max_temperature': '36', 'wind_direction': '东风'},
                ]
            }
        },
    )

    response = weather_query_service.build_weather_query_response(ChatRequest(question='查一下杭州天气', conversation_id='weather-heat'))

    weather = response['data']['weather']
    combined = f"{response['final_answer']} {' '.join(weather['weather_tips'])} {' '.join(weather['packing_tips'])}"
    assert weather['connected'] is True
    assert '防晒' in combined
    assert '补水' in combined
    assert '避开正午' in combined
    assert '帽子' in combined or '墨镜' in combined


def test_weather_query_accepts_tencent_realtime_payload(monkeypatch):
    from travel_agent.services import weather_query_service

    monkeypatch.setattr(weather_query_service.settings, 'tencent_maps_key', 'fake-key')
    monkeypatch.setattr(
        weather_query_service._client,
        'geocoder',
        lambda city, region=None: {'result': {'location': {'lat': 30.2741, 'lng': 120.1551}, 'ad_info': {'adcode': '330100'}}},
    )
    monkeypatch.setattr(
        weather_query_service._client,
        'weather_info',
        lambda adcode, weather_type=None: {
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
        },
    )

    response = weather_query_service.build_weather_query_response(ChatRequest(question='杭州天气怎么样', conversation_id='weather-realtime'))

    weather = response['data']['weather']
    combined = f"{response['final_answer']} {weather['summary']} {' '.join(weather['weather_tips'])} {' '.join(weather['packing_tips'])}"
    assert weather['connected'] is True
    assert weather['data_source'] == 'tencent_maps'
    assert weather['fallback_reason'] is None
    assert weather['daily_weather'][0]['weather'] == '晴天'
    assert weather['daily_weather'][0]['temperature'] == '36℃'
    assert '腾讯天气已接通' in combined
    assert '。。' not in response['final_answer']
    assert '防晒' in combined
    assert '补水' in combined
    assert '避开正午' in combined


def test_weather_query_uses_future_forecast_for_three_days(monkeypatch):
    from travel_agent.services import weather_query_service

    calls = []
    monkeypatch.setattr(weather_query_service.settings, 'tencent_maps_key', 'fake-key')
    monkeypatch.setattr(
        weather_query_service._client,
        'geocoder',
        lambda city, region=None: {'result': {'location': {'lat': 34.26, 'lng': 117.2}, 'ad_info': {'adcode': '320300'}}},
    )

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

    monkeypatch.setattr(weather_query_service._client, 'weather_info', fake_weather_info)

    response = weather_query_service.build_weather_query_response(ChatRequest(question='未来三天徐州天气怎么样', conversation_id='weather-three-days'))

    weather = response['data']['weather']
    assert calls == [('320300', 'future')]
    assert weather['connected'] is True
    assert weather['data_source'] == 'tencent_maps'
    assert len(weather['daily_weather']) == 3
    assert [item['weather'] for item in weather['daily_weather']] == ['晴天转小雨', '中雨转大雨', '多云转晴天']
    assert weather['daily_weather'][0]['temperature'] == '26-34℃'
    assert '未来3天' in response['final_answer']
    assert '。；' not in response['final_answer']


def test_weather_query_failure_reports_fallback_reason(monkeypatch):
    from travel_agent.services import weather_query_service

    monkeypatch.setattr(weather_query_service.settings, 'tencent_maps_key', '')

    response = weather_query_service.build_weather_query_response(ChatRequest(question='腾讯天气接通了吗', conversation_id='weather-fallback'))

    weather = response['data']['weather']
    combined = f"{response['final_answer']} {weather['summary']}"
    assert response['answer_type'] == 'weather_query'
    assert weather['connected'] is False
    assert weather['data_source'] == 'fallback'
    assert weather['fallback_reason']
    assert '腾讯天气未接通' in combined
    assert '今天下雨' not in combined
    assert '今天高温' not in combined
    assert '雨天优先室内' not in combined


@pytest.mark.asyncio
async def test_unified_graph_routes_weather_query(monkeypatch):
    from travel_agent.agent import travel_graph

    def fake_weather_response(request):
        return {
            'conversation_id': request.conversation_id,
            'answer_type': 'weather_query',
            'final_answer': '腾讯天气已接通。杭州天气可用。',
            'data': {'weather': {'connected': True, 'data_source': 'tencent_maps'}},
            'travel_request': None,
            'upload_context': None,
            'meta': {'source': 'weather_query'},
            'error': None,
        }

    monkeypatch.setattr(travel_graph, 'build_weather_query_response', fake_weather_response)

    state = await travel_graph.unified_graph.ainvoke({'request': ChatRequest(question='杭州天气怎么样', conversation_id='weather-graph')})

    assert state['answer_type'] == 'weather_query'
    assert state['data']['weather']['connected'] is True
