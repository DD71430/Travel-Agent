from __future__ import annotations

import re
from typing import Any

from travel_agent.core.config import get_settings
from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.intent_service import CITY_HINTS
from travel_agent.services.weather_service import build_daily_weather_brief, extract_tencent_weather_days
from travel_agent.tools.tencent_webservice_client import TencentWebServiceClient, TencentWebServiceError

settings = get_settings()
_client = TencentWebServiceClient()

_CONNECTIVITY_MARKERS = ('天气接口', '腾讯天气', '接通', '查天气')


def _dedupe_text(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        cleaned = str(item or '').strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _trim_sentence_end(text: str) -> str:
    return str(text or '').rstrip('。；;，, ')


def _extract_query_city(request: ChatRequest) -> tuple[str | None, bool]:
    source = f'{request.question or ""} {request.destination or ""}'.strip()
    for city in CITY_HINTS:
        if city in source:
            return city, False
    if request.destination and request.destination.strip():
        return request.destination.strip().replace('市', ''), False
    if any(marker in request.question for marker in _CONNECTIVITY_MARKERS):
        return '杭州', True
    match = re.search(r'([\u4e00-\u9fa5]{2,8})(?:市)?(?:天气|气温|下雨|降雨|高温)', request.question)
    if match:
        return match.group(1).replace('市', '').strip(), False
    return None, False


def _extract_location(payload: dict[str, Any]) -> str | None:
    result = payload.get('result') if isinstance(payload, dict) else {}
    location = result.get('location') if isinstance(result, dict) else {}
    lat = location.get('lat') if isinstance(location, dict) else None
    lng = location.get('lng') if isinstance(location, dict) else None
    if lat is None or lng is None:
        return None
    return f'{lat},{lng}'


def _extract_adcode(payload: dict[str, Any]) -> str | None:
    result = payload.get('result') if isinstance(payload, dict) else {}
    ad_info = result.get('ad_info') if isinstance(result, dict) else {}
    adcode = ad_info.get('adcode') if isinstance(ad_info, dict) else None
    return str(adcode) if adcode else None


def _resolve_city_adcode(city: str) -> tuple[str | None, dict[str, Any], str | None]:
    debug: dict[str, Any] = {'city': city}
    try:
        geocode = _client.geocoder(city, region=city)
        debug['geocoder_status'] = geocode.get('status')
    except TencentWebServiceError as exc:
        debug['geocoder_error'] = str(exc)
        return None, debug, 'geocoder_failed'
    adcode = _extract_adcode(geocode)
    location = _extract_location(geocode)
    if adcode:
        debug['adcode_source'] = 'geocoder'
        return adcode, debug, None
    if not location:
        return None, debug, 'missing_location'
    try:
        reverse = _client.reverse_geocoder(location)
        debug['reverse_status'] = reverse.get('status')
    except TencentWebServiceError as exc:
        debug['reverse_error'] = str(exc)
        return None, debug, 'reverse_geocoder_failed'
    adcode = _extract_adcode(reverse)
    if not adcode:
        return None, debug, 'missing_adcode'
    debug['adcode_source'] = 'reverse_geocoder'
    return adcode, debug, None


def _fallback_response(request: ChatRequest, city: str | None, reason: str, debug: dict[str, Any] | None = None, *, defaulted_city: bool = False) -> dict[str, Any]:
    safe_city = city or '未指定城市'
    default_note = '未指定城市，使用杭州进行连通性检测。' if defaulted_city else ''
    city_note = '' if city else '请指定城市，例如：杭州天气。'
    reason_text = reason or 'unknown'
    summary = f'腾讯天气未接通：{reason_text}。当前只能使用 fallback，不会做确定性天气判断。{city_note}'
    final_answer = f'{default_note}{summary}'
    return {
        'conversation_id': request.conversation_id or '',
        'answer_type': 'weather_query',
        'final_answer': final_answer,
        'data': {
            'weather': {
                'city': safe_city,
                'adcode': None,
                'connected': False,
                'data_source': 'fallback',
                'fallback_reason': reason_text,
                'summary': summary,
                'daily_weather': [],
                'weather_tips': ['天气待确认，建议指定城市并确认腾讯天气配置。'],
                'packing_tips': ['雨具、防晒、补水用品作为备选'],
                'debug': {'provider': 'fallback', 'fallback_reason': reason_text, **(debug or {})},
            }
        },
        'travel_request': None,
        'upload_context': None,
        'meta': {'source': 'weather_query'},
        'error': None,
    }


def build_weather_query_response(request: ChatRequest) -> dict[str, Any]:
    city, defaulted_city = _extract_query_city(request)
    if not city:
        return _fallback_response(request, None, 'missing_city')
    if not settings.tencent_maps_key:
        return _fallback_response(request, city, 'missing_key', defaulted_city=defaulted_city)
    adcode, debug, reason = _resolve_city_adcode(city)
    if not adcode:
        return _fallback_response(request, city, reason or 'missing_adcode', debug, defaulted_city=defaulted_city)
    try:
        payload = _client.weather_info(adcode, 'future')
    except TencentWebServiceError as exc:
        return _fallback_response(request, city, 'weather_api_error', {**debug, 'weather_error': str(exc)}, defaulted_city=defaulted_city)
    daily_weather = extract_tencent_weather_days(payload, city, 3, adcode=adcode)
    if not daily_weather:
        return _fallback_response(request, city, 'empty_forecast', debug, defaulted_city=defaulted_city)
    weather_context = {'data_source': 'tencent_maps', 'destination': city, 'daily_weather': daily_weather}
    daily_briefs = [build_daily_weather_brief(weather_context, day) for day in daily_weather]
    weather_tips = _dedupe_text([tip for day in daily_weather for tip in day.get('weather_tips', [])])
    packing_tips = _dedupe_text([tip for day in daily_weather for tip in day.get('packing_tips', [])])
    summary = f'{city}未来{len(daily_weather)}天天气：{"；".join(_trim_sentence_end(item) for item in daily_briefs)}'
    default_note = '未指定城市，使用杭州进行连通性检测。' if defaulted_city else ''
    advice = '；'.join(_trim_sentence_end(item) for item in weather_tips[:4]) if weather_tips else '建议按实时天气微调出行安排'
    final_answer = f'{default_note}腾讯天气已接通。{_trim_sentence_end(summary)}。{_trim_sentence_end(advice)}。'
    return {
        'conversation_id': request.conversation_id or '',
        'answer_type': 'weather_query',
        'final_answer': final_answer,
        'data': {
            'weather': {
                'city': city,
                'adcode': adcode,
                'connected': True,
                'data_source': 'tencent_maps',
                'fallback_reason': None,
                'summary': summary,
                'daily_weather': daily_weather,
                'weather_tips': weather_tips,
                'packing_tips': packing_tips,
                'debug': {'provider': 'tencent_maps', 'request_debug': debug},
            }
        },
        'travel_request': None,
        'upload_context': None,
        'meta': {'source': 'weather_query'},
        'error': None,
    }
