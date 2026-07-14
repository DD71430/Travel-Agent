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


def _dedupe_text(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        cleaned = str(item or '').strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _parse_temperature_bounds(temperature_text: str | None) -> tuple[float | None, float | None]:
    if not temperature_text:
        return None, None
    normalized = re.sub(r'(?<=\d)\s*[-~至]\s*(?=\d)', ' ', temperature_text)
    values = [float(item) for item in re.findall(r'(?<!\d)-?\d+(?:\.\d+)?', normalized)]
    if not values:
        return None, None
    return min(values), max(values)


def _weather_flags(weather_day: dict[str, Any] | None) -> dict[str, Any]:
    day = weather_day or {}
    weather = str(day.get('weather') or '')
    low_temp, high_temp = _parse_temperature_bounds(str(day.get('temperature') or ''))
    has_extreme = any(keyword in weather for keyword in _EXTREME_WEATHER)
    has_rain = (has_extreme and any(keyword in weather for keyword in ('雨', '雷', '暴'))) or any(keyword in weather for keyword in _RAIN_WEATHER)
    has_sun = any(keyword in weather for keyword in ('晴', '多云', '少云'))
    has_heat = high_temp is not None and high_temp >= 30
    has_extreme_heat = high_temp is not None and high_temp >= 35
    return {
        'has_extreme': has_extreme,
        'has_rain': has_rain,
        'has_sun': has_sun,
        'has_heat': has_heat,
        'has_extreme_heat': has_extreme_heat,
        'high_temp': high_temp,
        'low_temp': low_temp,
    }


def weather_badge_for_day(weather_context: dict[str, Any], weather_day: dict[str, Any] | None) -> str | None:
    if not weather_day:
        return None
    day_source = str(weather_day.get('data_source') or weather_context.get('data_source') or '')
    if day_source != 'tencent_maps':
        return '天气待确认'
    flags = _weather_flags(weather_day)
    if flags['has_extreme']:
        return '预警'
    if flags['has_rain']:
        return '雨天'
    if flags['has_extreme_heat'] or flags['has_heat']:
        return '高温'
    if flags['has_sun']:
        return '晴热'
    return '天气参考'


def build_daily_weather_brief(weather_context: dict[str, Any], weather_day: dict[str, Any] | None) -> str:
    if not weather_day:
        return '天气待确认，未做确定性天气重排；建议出行前查看实时天气。'
    city = _safe_city(str(weather_day.get('city') or weather_context.get('destination') or '目的地'))
    day = weather_day.get('day')
    prefix = f'第{day}天{city}' if day else city
    day_source = str(weather_day.get('data_source') or weather_context.get('data_source') or '')
    if day_source != 'tencent_maps':
        return f'{prefix}天气待确认，未做确定性天气重排；建议出行前查看实时天气。'
    weather = str(weather_day.get('weather') or '天气待确认')
    temperature = str(weather_day.get('temperature') or '温度待确认')
    flags = _weather_flags(weather_day)
    actions: list[str] = []
    if flags['has_rain']:
        actions.append('带伞/雨衣并注意防滑，优先室内或遮蔽点位')
    if flags['has_heat']:
        actions.append('防晒、补水，携带帽子或墨镜')
    if flags['has_extreme_heat']:
        actions.append('避开正午户外暴晒')
    if flags['has_extreme']:
        actions.append('减少户外、关注预警')
    if not actions:
        actions.append(str(weather_day.get('strategy') or '按实时天气微调室内外顺序'))
    return f'{prefix}：{weather}，{temperature}；{"；".join(_dedupe_text(actions))}。'


def build_daily_weather_adjustments(weather_context: dict[str, Any], weather_day: dict[str, Any] | None) -> list[str]:
    if not weather_day:
        return []
    day_source = str(weather_day.get('data_source') or weather_context.get('data_source') or '')
    if day_source != 'tencent_maps':
        return []
    day = weather_day.get('day')
    city = _safe_city(str(weather_day.get('city') or weather_context.get('destination') or '目的地'))
    prefix = f'第{day}天{city}' if day else city
    flags = _weather_flags(weather_day)
    adjustments: list[str] = []
    if flags['has_rain']:
        adjustments.append(f'{prefix}因降雨将博物馆、纪念馆、美术馆、科技馆等室内或遮蔽点位前置，湖边、公园、步道压缩游览或改为备选。')
    if flags['has_heat']:
        adjustments.append(f'{prefix}因高温将户外点位尽量安排在早晨或傍晚，中午安排室内景点、午餐、休整或酒店入住。')
    if flags['has_extreme']:
        adjustments.append(f'{prefix}存在暴雨/雷暴等风险，应减少户外停留并关注当地预警。')
    return _dedupe_text(adjustments)


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


def build_weather_tips(weather_day: dict[str, Any], *, data_source: str) -> dict[str, list[str]]:
    if data_source != 'tencent_maps':
        return {
            'weather_tags': ['weather_unconfirmed'],
            'weather_tips': [
                '天气待确认，建议出行前查看实时天气，不做确定性天气重排。',
            ],
            'packing_tips': ['天气待确认，保留雨具、防晒和补水用品作为备选'],
        }

    weather = str(weather_day.get('weather') or '')
    temperature = str(weather_day.get('temperature') or '')
    low_temp, high_temp = _parse_temperature_bounds(temperature)
    tags: list[str] = []
    tips: list[str] = []
    packing: list[str] = []
    has_extreme = any(keyword in weather for keyword in _EXTREME_WEATHER)
    has_rain = has_extreme and any(keyword in weather for keyword in ('雨', '雷', '暴')) or any(keyword in weather for keyword in _RAIN_WEATHER)
    has_sun = any(keyword in weather for keyword in ('晴', '多云', '少云'))

    if has_rain:
        tags.append('rain')
        tips.append('有降雨风险，建议携带雨伞或轻便雨衣。')
        tips.append('室外石板路、湖边步道或台阶区域注意防滑。')
        packing.extend(['雨伞或轻便雨衣', '防滑鞋'])
    if has_extreme:
        tags.append('weather_risk')
        tips.append('强降雨、雷暴或大风天气应减少户外停留，并关注当地预警。')

    if high_temp is not None and high_temp >= 30 or has_sun and high_temp is not None and high_temp >= 28:
        tags.append('sun_exposure')
        tips.append('日晒较强，注意防晒、补水。')
        packing.extend(['防晒霜', '遮阳帽或墨镜', '水杯'])
    if high_temp is not None and high_temp >= 35:
        tags.append('heat')
        tips.append('高温天气建议避开正午户外暴晒，把户外景点放在上午或傍晚。')

    if low_temp is not None and low_temp <= 0:
        tags.append('cold')
        tips.append('气温较低，建议增加保暖衣物，并减少长时间户外步行。')
        packing.append('保暖外套')

    if not tips:
        tags.append('weather_normal')
        tips.append('天气风险较低，按实时预报微调室内外顺序即可。')

    return {
        'weather_tags': _dedupe_text(tags),
        'weather_tips': _dedupe_text(tips),
        'packing_tips': _dedupe_text(packing),
    }


def build_weather_plan_summary(weather_context: dict[str, Any], daily_itinerary: list[Any]) -> dict[str, Any]:
    daily_weather = weather_context.get('daily_weather') if isinstance(weather_context.get('daily_weather'), list) else []
    daily_weather = [item for item in daily_weather if isinstance(item, dict)]
    data_source = str(weather_context.get('data_source') or '')
    has_real_weather = data_source == 'tencent_maps' or any(str(item.get('data_source') or '') == 'tencent_maps' for item in daily_weather)
    if not has_real_weather:
        daily_briefs = [build_daily_weather_brief(weather_context, item) for item in daily_weather]
        if not daily_briefs:
            daily_briefs = ['天气待确认，建议出行前查看实时天气；保留雨具、防晒和补水用品作为备选。']
        return {
            'weather_overview': '天气待确认，建议出行前查看实时天气；保留雨具、防晒和补水用品作为备选。',
            'daily_weather_briefs': daily_briefs,
            'weather_adjustments': ['天气待确认，不做确定性天气重排；建议出行前查看实时天气，保留室内/室外备选。'],
            'packing_summary': ['雨具、防晒和补水用品作为备选'],
        }

    daily_briefs = [build_daily_weather_brief(weather_context, item) for item in daily_weather]
    weather_adjustments = _dedupe_text([adjustment for item in daily_weather for adjustment in build_daily_weather_adjustments(weather_context, item)])
    packing_summary: list[str] = []
    rain_days = 0
    heat_days = 0
    extreme_days = 0
    for item in daily_weather:
        if str(item.get('data_source') or data_source) != 'tencent_maps':
            continue
        flags = _weather_flags(item)
        if flags['has_rain']:
            rain_days += 1
            packing_summary.extend(['雨伞或轻便雨衣', '防滑鞋'])
        if flags['has_heat']:
            heat_days += 1
            packing_summary.extend(['防晒霜', '水杯', '遮阳帽或墨镜'])
        if flags['has_extreme_heat']:
            packing_summary.append('轻薄透气衣物')
        if flags['has_extreme']:
            extreme_days += 1
        explicit_packing = item.get('packing_tips') if isinstance(item.get('packing_tips'), list) else []
        packing_summary.extend(str(tip) for tip in explicit_packing)
    overview_parts: list[str] = []
    if rain_days:
        overview_parts.append(f'{rain_days}天有降雨，行程已加入带伞/雨衣、防滑和优先室内或遮蔽点位安排')
    if heat_days:
        overview_parts.append(f'{heat_days}天达到晴热/高温，行程已加入防晒、补水和避开正午户外暴晒安排')
    if extreme_days:
        overview_parts.append('存在暴雨/雷暴等风险的日期已提示减少户外、关注预警')
    if not overview_parts:
        overview_parts.append(str(weather_context.get('summary') or '天气风险较低，按实时天气微调室内外顺序即可'))
    if daily_itinerary:
        overview_parts.append(f'已覆盖{len(daily_itinerary)}天每日天气卡片')
    return {
        'weather_overview': '；'.join(_dedupe_text(overview_parts)) + '。',
        'daily_weather_briefs': daily_briefs,
        'weather_adjustments': weather_adjustments,
        'packing_summary': _dedupe_text(packing_summary) or ['按实时天气准备常规出行装备'],
    }


def _safe_city(value: str | None) -> str:
    return (value or '目的地').replace('市', '').strip() or '目的地'


def _fallback_daily_weather(destination: str, route_stops: list[dict[str, Any]] | None, days: int) -> list[dict[str, Any]]:
    stop_names = [str(item.get('name') or '').strip() for item in (route_stops or []) if str(item.get('name') or '').strip()]
    cities = [*stop_names, *([destination] * max(1, days))]
    daily: list[dict[str, Any]] = []
    for index in range(1, max(1, days) + 1):
        city = _safe_city(cities[index - 1] if index - 1 < len(cities) else destination)
        tips = build_weather_tips({'weather': '天气待确认', 'temperature': '温度待确认'}, data_source='fallback')
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
                'data_source': 'fallback',
                'fallback_reason': 'missing_key_or_weather_unavailable',
                'adcode': None,
                **tips,
            }
        )
    return daily


def _format_realtime_temperature(value: Any) -> str:
    if value is None:
        return '温度待确认'
    text = str(value).strip()
    if not text:
        return '温度待确认'
    return text if '℃' in text or '°' in text else f'{text}℃'


def _combine_weather(day_weather: Any, night_weather: Any) -> str:
    day_text = str(day_weather or '').strip()
    night_text = str(night_weather or '').strip()
    if day_text and night_text and day_text != night_text:
        return f'{day_text}转{night_text}'
    return day_text or night_text or '天气未知'


def _temperature_range(day_temp: Any, night_temp: Any) -> str:
    values = [value for value in (day_temp, night_temp) if value is not None and str(value).strip()]
    if len(values) == 2:
        parsed = _parse_temperature_bounds(f'{values[0]} {values[1]}')
        if parsed[0] is not None and parsed[1] is not None:
            low = int(parsed[0]) if parsed[0].is_integer() else parsed[0]
            high = int(parsed[1]) if parsed[1].is_integer() else parsed[1]
            return f'{low}-{high}℃'
    if values:
        return _format_realtime_temperature(values[0])
    return '温度待确认'


def _forecast_info_to_weather_item(info: dict[str, Any]) -> dict[str, Any]:
    day = info.get('day') if isinstance(info.get('day'), dict) else {}
    night = info.get('night') if isinstance(info.get('night'), dict) else {}
    weather = _combine_weather(day.get('weather'), night.get('weather'))
    return {
        'weather': weather,
        'temperature': _temperature_range(day.get('temperature'), night.get('temperature')),
        'wind_direction': day.get('wind_direction') or night.get('wind_direction'),
        'wind': day.get('wind_power') or night.get('wind_power'),
        'date': info.get('date'),
        'week': info.get('week'),
    }


def _forecast_items_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get('result') if isinstance(payload, dict) else {}
    forecasts = (result or {}).get('forecast') or (result or {}).get('forecasts') or []
    if isinstance(forecasts, dict):
        forecasts = [forecasts]
    if isinstance(forecasts, list) and forecasts:
        items: list[dict[str, Any]] = []
        for item in forecasts:
            if not isinstance(item, dict):
                continue
            infos = item.get('infos')
            if isinstance(infos, list):
                items.extend(_forecast_info_to_weather_item(info) for info in infos if isinstance(info, dict))
                continue
            if isinstance(infos, dict):
                items.append({**item, **infos})
                continue
            items.append(item)
        return items
    realtime = (result or {}).get('realtime') or []
    if isinstance(realtime, dict):
        realtime = [realtime]
    if not isinstance(realtime, list):
        return []
    items: list[dict[str, Any]] = []
    for item in realtime:
        if not isinstance(item, dict):
            continue
        infos = item.get('infos') if isinstance(item.get('infos'), dict) else item
        weather_item = {
            'weather': infos.get('weather') or item.get('weather') or '天气未知',
            'temperature': _format_realtime_temperature(infos.get('temperature') or item.get('temperature')),
            'wind_direction': infos.get('wind_direction') or item.get('wind_direction'),
            'wind': infos.get('wind_power') or infos.get('wind_power_v2') or item.get('wind'),
        }
        items.append(weather_item)
    return items


def extract_tencent_weather_days(payload: dict[str, Any], city: str, days: int, *, start_day: int = 1, adcode: str | None = None) -> list[dict[str, Any]]:
    forecasts = _forecast_items_from_payload(payload)
    daily: list[dict[str, Any]] = []
    for offset, item in enumerate(forecasts[:days]):
        if not isinstance(item, dict):
            continue
        index = start_day + offset
        weather = str(item.get('weather') or item.get('day_weather') or item.get('night_weather') or '天气未知')
        low = item.get('min_temperature') or item.get('min_temp') or item.get('night_air_temperature')
        high = item.get('max_temperature') or item.get('max_temp') or item.get('day_air_temperature')
        temperature = f'{low}-{high}℃' if low is not None and high is not None else str(item.get('temperature') or '温度待确认')
        suitability = classify_weather_suitability(weather, temperature)
        tips = build_weather_tips({'weather': weather, 'temperature': temperature}, data_source='tencent_maps')
        daily.append(
            {
                'day': index,
                'city': city,
                'weather': weather,
                'temperature': temperature,
                'wind': str(item.get('wind_direction') or item.get('wind') or '风力待确认'),
                'data_source': 'tencent_maps',
                'fallback_reason': None,
                'adcode': adcode,
                **suitability,
                **tips,
            }
        )
    return daily


def _extract_forecasts(payload: dict[str, Any], city: str, days: int, *, start_day: int = 1, adcode: str | None = None) -> list[dict[str, Any]]:
    return extract_tencent_weather_days(payload, city, days, start_day=start_day, adcode=adcode)


def _route_weather_targets(destination: str, route_stops: list[dict[str, Any]] | None, days: int, location_debug: dict[str, Any] | None) -> list[dict[str, Any]]:
    stops = [item for item in (route_stops or []) if isinstance(item, dict)]
    destination_adcode = None
    if isinstance(location_debug, dict):
        destination_adcode = location_debug.get('destination_adcode') or location_debug.get('adcode')
    targets: list[dict[str, Any]] = []
    for index in range(days):
        stop = stops[index] if index < len(stops) else {}
        city = _safe_city(str(stop.get('name') or destination))
        adcode = stop.get('adcode') or stop.get('ad_code') or stop.get('city_adcode')
        if not adcode and isinstance(location_debug, dict):
            adcode = location_debug.get(f'waypoint_adcode:{city}') or location_debug.get(f'waypoint_adcode:{city}市')
        if not adcode and _safe_city(city) == _safe_city(destination):
            adcode = destination_adcode
        targets.append({'day': index + 1, 'city': city, 'adcode': str(adcode) if adcode else None})
    return targets


def _same_weather_target(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return bool(left.get('adcode')) and left.get('adcode') == right.get('adcode') and _safe_city(str(left.get('city') or '')) == _safe_city(str(right.get('city') or ''))


def build_weather_context(destination: str, route_stops: list[dict[str, Any]] | None = None, days: int = 3, location_debug: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_days = max(1, days)
    targets = _route_weather_targets(destination, route_stops, safe_days, location_debug)
    if settings.tencent_maps_key and any(target.get('adcode') for target in targets):
        daily_weather: list[dict[str, Any]] = []
        target_index = 0
        while target_index < len(targets):
            target = targets[target_index]
            adcode = target.get('adcode')
            if not adcode:
                fallback = _fallback_daily_weather(str(target.get('city') or destination), [], 1)[0]
                fallback.update({'day': target['day'], 'city': target.get('city') or destination, 'fallback_reason': 'missing_adcode'})
                daily_weather.append(fallback)
                target_index += 1
                continue
            span = 1
            while target_index + span < len(targets) and _same_weather_target(target, targets[target_index + span]):
                span += 1
            try:
                payload = _client.weather_info(str(adcode), 'future')
                extracted = _extract_forecasts(payload, str(target.get('city') or destination), span, start_day=int(target['day']), adcode=str(adcode))
                if extracted:
                    daily_weather.extend(extracted)
                    for missing_offset in range(len(extracted), span):
                        missing_target = targets[target_index + missing_offset]
                        fallback = _fallback_daily_weather(str(missing_target.get('city') or destination), [], 1)[0]
                        fallback.update({'day': missing_target['day'], 'city': missing_target.get('city') or destination, 'fallback_reason': 'empty_weather_forecast'})
                        daily_weather.append(fallback)
                    target_index += span
                    continue
                fallback_reason = 'empty_weather_forecast'
            except TencentWebServiceError:
                fallback_reason = 'weather_service_error'
            for offset in range(span):
                missing_target = targets[target_index + offset]
                fallback = _fallback_daily_weather(str(missing_target.get('city') or destination), [], 1)[0]
                fallback.update({'day': missing_target['day'], 'city': missing_target.get('city') or destination, 'fallback_reason': fallback_reason})
                daily_weather.append(fallback)
            target_index += span
        if daily_weather and any(item.get('data_source') == 'tencent_maps' for item in daily_weather):
            all_real = all(item.get('data_source') == 'tencent_maps' for item in daily_weather)
            indoor_days = sum(1 for item in daily_weather if item.get('indoor_priority'))
            weather_samples = '、'.join(_dedupe_text([str(item.get('weather') or '') for item in daily_weather[:3] if item.get('weather')]))
            summary = f'{_safe_city(destination)}未来{len(daily_weather)}天天气参考：{weather_samples or daily_weather[0]["weather"]}；{"建议优先安排室内景点" if indoor_days else "天气适合室外游览"}。'
            fallback_reasons = _dedupe_text([str(item.get('fallback_reason')) for item in daily_weather if item.get('fallback_reason')])
            return {
                'data_source': 'tencent_maps' if all_real else 'mixed',
                'destination': destination,
                'summary': summary,
                'daily_weather': daily_weather,
                'warnings': [] if all_real else ['weather_partial_fallback'],
                'request_debug': {'provider': 'tencent_maps' if all_real else 'mixed', 'fallback_reason': None if all_real else 'partial_fallback', 'daily_fallback_reasons': fallback_reasons},
            }
    daily_weather = _fallback_daily_weather(destination, route_stops, safe_days)
    return {
        'data_source': 'fallback',
        'destination': destination,
        'summary': f'{_safe_city(destination)}天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。',
        'daily_weather': daily_weather,
        'warnings': ['weather_fallback'],
        'request_debug': {'provider': 'fallback', 'fallback_reason': 'missing_key_or_weather_unavailable'},
    }
