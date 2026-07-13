from __future__ import annotations

import re
from typing import Any

from travel_agent.core.config import get_settings
from travel_agent.tools.tencent_webservice_client import TencentWebServiceClient, TencentWebServiceError

settings = get_settings()
_client = TencentWebServiceClient()

_EXTREME_WEATHER = ('暴雨', '大暴雨', '特大暴雨', '台风', '沙尘', '雷暴', '大风', '冰雹')
_RAIN_WEATHER = ('雨', '阵雨', '雷阵雨', '大雨', '中雨', '小雨')
_GOOD_WEATHER = ('晴', '多云', '阴')


def _parse_temperature_bounds(temperature_text: str | None) -> tuple[float | None, float | None]:
    if not temperature_text:
        return None, None
    values = [float(item) for item in re.findall(r'-?\d+(?:\.\d+)?', temperature_text)]
    if not values:
        return None, None
    return min(values), max(values)


def classify_weather_suitability(weather_text: str | None, temperature_text: str | None = None) -> dict[str, Any]:
    weather = weather_text or ''
    low_temp, high_temp = _parse_temperature_bounds(temperature_text)
    if any(keyword in weather for keyword in _EXTREME_WEATHER):
        result = {
            'risk_level': 'high',
            'outdoor_suitability': 'poor',
            'indoor_priority': True,
            'strategy': '极端天气风险较高，优先安排博物馆、美术馆、纪念馆等室内景点，不建议强行安排山岳步道等户外项目。',
        }
    elif any(keyword in weather for keyword in _RAIN_WEATHER):
        result = {
            'risk_level': 'medium',
            'outdoor_suitability': 'limited',
            'indoor_priority': True,
            'strategy': '有降雨风险，优先安排博物馆、美术馆、纪念馆等室内景点，室外景点建议视天气压缩停留。',
        }
    elif any(keyword in weather for keyword in _GOOD_WEATHER):
        result = {
            'risk_level': 'low',
            'outdoor_suitability': 'good',
            'indoor_priority': False,
            'strategy': '天气适合室外游览，可安排公园、古城、湖泊、步道和自然风光。',
        }
    else:
        result = {
            'risk_level': 'unknown',
            'outdoor_suitability': 'unknown',
            'indoor_priority': False,
            'strategy': '天气信息有限，建议出行前再次确认实时天气，并保留室内备选。',
        }
    if high_temp is not None and high_temp >= 35:
        result.update(
            {
                'risk_level': 'medium' if result['risk_level'] != 'high' else 'high',
                'outdoor_suitability': 'limited' if result['outdoor_suitability'] != 'poor' else 'poor',
                'indoor_priority': True,
                'strategy': f"{result['strategy']} 高温天气，中午避免室外，户外景点尽量安排在上午或傍晚。",
            }
        )
    if low_temp is not None and low_temp <= 0:
        result.update(
            {
                'risk_level': 'medium' if result['risk_level'] != 'high' else 'high',
                'outdoor_suitability': 'limited' if result['outdoor_suitability'] != 'poor' else 'poor',
                'indoor_priority': True,
                'strategy': f"{result['strategy']} 严寒天气，优先安排室内景点并减少长时间户外步行。",
            }
        )
    return result


def _safe_city(value: str | None) -> str:
    return (value or '目的地').replace('市', '').strip() or '目的地'


def _fallback_daily_weather(destination: str, route_stops: list[dict[str, Any]] | None, days: int) -> list[dict[str, Any]]:
    stop_names = [str(item.get('name') or '').strip() for item in (route_stops or []) if str(item.get('name') or '').strip()]
    cities = [*stop_names, *([destination] * max(1, days))]
    daily: list[dict[str, Any]] = []
    for index in range(1, max(1, days) + 1):
        city = _safe_city(cities[index - 1] if index - 1 < len(cities) else destination)
        daily.append(
            {
                'day': index,
                'city': city,
                'weather': '天气待确认',
                'temperature': '温度待确认',
                'wind': '以实时预报为准',
                'risk_level': 'unknown',
                'outdoor_suitability': 'unknown',
                'indoor_priority': False,
                'strategy': '天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。',
            }
        )
    return daily


def _extract_forecasts(payload: dict[str, Any], city: str, days: int) -> list[dict[str, Any]]:
    result = payload.get('result') if isinstance(payload, dict) else {}
    forecasts = (result or {}).get('forecast') or (result or {}).get('forecasts') or []
    if isinstance(forecasts, dict):
        forecasts = [forecasts]
    if not isinstance(forecasts, list):
        return []
    daily: list[dict[str, Any]] = []
    for index, item in enumerate(forecasts[:days], start=1):
        if not isinstance(item, dict):
            continue
        weather = str(item.get('weather') or item.get('day_weather') or item.get('night_weather') or '天气未知')
        low = item.get('min_temperature') or item.get('min_temp') or item.get('night_air_temperature')
        high = item.get('max_temperature') or item.get('max_temp') or item.get('day_air_temperature')
        temperature = f'{low}-{high}℃' if low is not None and high is not None else str(item.get('temperature') or '温度待确认')
        suitability = classify_weather_suitability(weather, temperature)
        daily.append(
            {
                'day': index,
                'city': city,
                'weather': weather,
                'temperature': temperature,
                'wind': str(item.get('wind_direction') or item.get('wind') or '风力待确认'),
                **suitability,
            }
        )
    return daily


def build_weather_context(destination: str, route_stops: list[dict[str, Any]] | None = None, days: int = 3, location_debug: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_days = max(1, days)
    adcode = None
    if isinstance(location_debug, dict):
        adcode = location_debug.get('destination_adcode') or location_debug.get('adcode')
    if settings.tencent_maps_key and adcode:
        try:
            payload = _client.weather_info(str(adcode))
            daily_weather = _extract_forecasts(payload, _safe_city(destination), safe_days)
            if daily_weather:
                indoor_days = sum(1 for item in daily_weather if item.get('indoor_priority'))
                summary = f'{_safe_city(destination)}未来{len(daily_weather)}天天气参考：{daily_weather[0]["weather"]}；{"建议优先安排室内景点" if indoor_days else "天气适合室外游览"}。'
                return {
                    'data_source': 'tencent_maps',
                    'destination': destination,
                    'summary': summary,
                    'daily_weather': daily_weather,
                    'warnings': [],
                    'request_debug': {'provider': 'tencent_maps', 'fallback_reason': None},
                }
        except TencentWebServiceError:
            pass
    daily_weather = _fallback_daily_weather(destination, route_stops, safe_days)
    return {
        'data_source': 'fallback',
        'destination': destination,
        'summary': f'{_safe_city(destination)}天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。',
        'daily_weather': daily_weather,
        'warnings': ['weather_fallback'],
        'request_debug': {'provider': 'fallback', 'fallback_reason': 'missing_key_or_weather_unavailable'},
    }
