from __future__ import annotations

import re
from typing import Any, Literal

from travel_agent.models.travel import TravelPlanRequest
from travel_agent.services.intent_service import extract_locations, extract_question_waypoints, extract_travel_mode, extract_trip_details

TripType = Literal['destination_trip', 'along_route_trip', 'commute', 'nearby_search', 'general_chat']

INTEREST_TAG_RULES: dict[str, tuple[str, ...]] = {
    '博物馆': ('博物馆', '纪念馆', '美术馆', '科技馆', '展览', '展馆'),
    '公园': ('公园', '湿地', '湖泊', '步道', '绿道'),
    '古城': ('古城', '古镇', '城墙', '古迹'),
    '历史文化': ('历史', '文化', '遗址', '寺庙', '非遗', '老街', '文化街区'),
    '美食': ('美食', '小吃', '老字号', '夜市', '地方菜', '餐厅'),
    '自然风光': ('自然', '风景', '湖', '山', '湿地', '森林', '滨河'),
    '亲子': ('亲子', '孩子', '小朋友', '儿童', '乐园', '动物园', '海洋馆'),
    '购物': ('购物', '商场', '商业街'),
    '夜景': ('夜景', '夜游', '灯光', '傍晚'),
    '老人友好': ('老人', '长辈', '少走路', '不太累', '轻松'),
}

AVOID_TAG_RULES: dict[str, tuple[str, ...]] = {
    '不爬山': ('不爬山', '不要爬山', '别爬山', '不登山'),
    '不逛商场': ('不逛商场', '不要商场', '不购物'),
    '不太累': ('不太累', '别太累', '轻松点', '少折腾'),
    '少走路': ('少走路', '少步行', '不想走太多'),
}

_CHINESE_NUMERAL_MAP = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def parse_cn_number(text: str | None) -> int | None:
    if text is None:
        return None
    cleaned = str(text).strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return int(cleaned)
    if cleaned in _CHINESE_NUMERAL_MAP:
        return _CHINESE_NUMERAL_MAP[cleaned]
    if cleaned.startswith('十') and len(cleaned) == 2:
        return 10 + _CHINESE_NUMERAL_MAP.get(cleaned[1], 0)
    if cleaned.endswith('十') and len(cleaned) == 2:
        return _CHINESE_NUMERAL_MAP.get(cleaned[0], 0) * 10
    if '十' in cleaned and len(cleaned) == 3:
        return _CHINESE_NUMERAL_MAP.get(cleaned[0], 0) * 10 + _CHINESE_NUMERAL_MAP.get(cleaned[2], 0)
    return None


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def extract_interest_tags(text: str | None) -> list[str]:
    source = text or ''
    tags: list[str] = []
    for tag, keywords in INTEREST_TAG_RULES.items():
        if any(keyword in source for keyword in keywords):
            tags.append(tag)
    return _dedupe(tags)


def extract_avoid_tags(text: str | None) -> list[str]:
    source = text or ''
    tags: list[str] = []
    for tag, keywords in AVOID_TAG_RULES.items():
        if any(keyword in source for keyword in keywords):
            tags.append(tag)
    return _dedupe(tags)


def extract_pace(text: str | None) -> Literal['relaxed', 'normal', 'intensive']:
    source = text or ''
    if any(keyword in source for keyword in ('轻松', '慢游', '休闲', '不赶', '不太累', '少走路', '老人', '长辈')):
        return 'relaxed'
    if any(keyword in source for keyword in ('紧凑', '多安排', '尽量多', '特种兵', '高强度')):
        return 'intensive'
    return 'normal'


def _first_number_for_patterns(source: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, source)
        if match:
            parsed = parse_cn_number(match.group('num'))
            if parsed is not None:
                return parsed
    return None


def _parse_explicit_total_days(source: str) -> int | None:
    return _first_number_for_patterns(
        source,
        (
            r'(?:总共|一共|共|总计|全程|整体|总行程|总时长)\s*(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
            r'(?P<num>\d+|[一二两三四五六七八九十]+)\s*天(?:总共|一共|全程|总行程)',
        ),
    )


def parse_stage_days(text: str | None) -> dict[str, int | None | str]:
    source = text or ''
    route_no_play = bool(re.search(r'(中途|路上|沿途|途中)(?:不|不用|不要|不安排)(?:玩|游玩|景点|停留)', source))
    destination_no_play = bool(re.search(r'(目的地|到达后|到了[^，。；,]*|到[^，。；,]{1,12})(?:不|不用|不要)(?:玩|游玩|停留)|到了就返程', source))
    route_days = 0 if route_no_play else _first_number_for_patterns(
        source,
        (
            r'(?:途中|路上|沿途|中途)(?:边走边玩|游玩|玩|安排|慢慢玩)?(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
            r'(?:途中|路上|沿途|中途).*?(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
        ),
    )
    destination_days = 0 if destination_no_play else _first_number_for_patterns(
        source,
        (
            r'(?:目的地|到目的地|目的地深度游)(?:游玩|玩|安排|深度游)?(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
            r'(?:到了|到|在)(?:目的地|[^，。；,\s]{1,12})(?:后|再)?(?:游玩|玩|安排|深度游)?(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
        ),
    )
    route_nights = _first_number_for_patterns(
        source,
        (
            r'(?:路上|途中|沿途)(?:只)?(?:住|住宿)(?P<num>\d+|[一二两三四五六七八九十]+)\s*晚',
            r'(?:路上|途中|沿途).*?(?P<num>\d+|[一二两三四五六七八九十]+)\s*晚',
        ),
    )
    destination_nights = _first_number_for_patterns(
        source,
        (
            r'(?:目的地|到目的地|到了[^，。；,]*|到[^，。；,]{1,12})(?:住|住宿)(?P<num>\d+|[一二两三四五六七八九十]+)\s*晚',
            r'(?:目的地|到目的地|到了[^，。；,]*|到[^，。；,]{1,12}).*?(?P<num>\d+|[一二两三四五六七八九十]+)\s*晚',
        ),
    )
    if route_days is not None and destination_days is not None:
        stage_plan_mode = 'route_then_destination' if route_days > 0 and destination_days > 0 else 'destination_only' if route_days == 0 else 'route_only'
        total_days_source = 'stage_sum'
    elif route_days is not None:
        stage_plan_mode = 'route_only' if route_days > 0 else 'destination_only'
        total_days_source = 'stage_sum' if route_days == 0 else 'inferred'
    elif destination_days is not None:
        stage_plan_mode = 'destination_only' if destination_days > 0 else 'route_only'
        total_days_source = 'stage_sum' if destination_days == 0 else 'inferred'
    else:
        stage_plan_mode = 'mixed_unspecified'
        total_days_source = 'inferred'
    return {
        'route_days': route_days,
        'destination_days': destination_days,
        'route_nights': route_nights,
        'destination_nights': destination_nights,
        'total_days_source': total_days_source,
        'stage_plan_mode': stage_plan_mode,
    }


def _looks_cross_city(origin: str | None, destination: str | None) -> bool:
    if not origin or not destination:
        return False
    origin_clean = origin.replace('市', '').strip()
    destination_clean = destination.replace('市', '').strip()
    return bool(origin_clean and destination_clean and origin_clean != destination_clean)


def build_trip_profile_from_text(text: str | None, *, origin: str | None = None, destination: str | None = None, travel_mode: str | None = None) -> dict[str, Any]:
    source = text or ''
    parsed_origin, parsed_destination = extract_locations(source)
    trip_details = extract_trip_details(source)
    mode = extract_travel_mode(source, travel_mode)
    explicit_total_days = _parse_explicit_total_days(source)
    duration_days = int(trip_details['duration_days']) if trip_details.get('duration_days') else None
    nights = int(trip_details['nights']) if trip_details.get('nights') else None
    stage_days = parse_stage_days(source)
    route_days = stage_days.get('route_days')
    destination_days = stage_days.get('destination_days')
    if isinstance(route_days, int) and isinstance(destination_days, int):
        stage_sum = route_days + destination_days
        if explicit_total_days is not None and explicit_total_days > stage_sum:
            duration_days = explicit_total_days
            total_days_source = 'explicit_total'
        else:
            duration_days = stage_sum
            total_days_source = 'stage_sum'
    else:
        total_days_source = 'explicit_total' if duration_days is not None else str(stage_days.get('total_days_source') or 'inferred')
        if duration_days is None and isinstance(route_days, int):
            duration_days = route_days
        if duration_days is None and isinstance(destination_days, int):
            duration_days = destination_days
    if duration_days is None and nights is not None:
        duration_days = nights + 1
    if duration_days is None:
        duration_days = 2 if any(keyword in source for keyword in ('周末', '两天', '二天')) else 3
    merged_origin = origin or parsed_origin
    merged_destination = destination or parsed_destination
    interest_tags = extract_interest_tags(source)
    avoid_tags = extract_avoid_tags(source)
    pace = extract_pace(source)
    trip_type = decide_trip_type(
        {
            'origin': merged_origin,
            'destination': merged_destination,
            'travel_mode': mode,
            'duration_days': duration_days,
            'interest_tags': interest_tags,
            'avoid_tags': avoid_tags,
            'pace': pace,
            'source_text': source,
        },
        None,
    )
    return {
        'origin': merged_origin,
        'destination': merged_destination,
        'travel_mode': mode,
        'duration_days': duration_days,
        'nights': nights,
        'budget': trip_details.get('budget'),
        'waypoints': extract_question_waypoints(source),
        'interest_tags': interest_tags,
        'avoid_tags': avoid_tags,
        'pace': pace,
        'trip_type': trip_type,
        'route_days': route_days,
        'destination_days': destination_days,
        'route_nights': stage_days.get('route_nights'),
        'destination_nights': stage_days.get('destination_nights'),
        'total_days_source': total_days_source,
        'stage_plan_mode': stage_days.get('stage_plan_mode'),
        'explicit_total_days': explicit_total_days,
    }


def build_trip_profile(request: TravelPlanRequest) -> dict[str, Any]:
    combined = '；'.join(part for part in [request.source_query, request.preferences] if part)
    profile = build_trip_profile_from_text(combined, origin=request.origin, destination=request.destination, travel_mode=request.travel_mode)
    base = dict(request.trip_profile or {})
    base.update({key: value for key, value in profile.items() if value not in (None, [], '')})
    base.setdefault('duration_days', profile['duration_days'])
    base.setdefault('interest_tags', profile['interest_tags'])
    base.setdefault('avoid_tags', profile['avoid_tags'])
    base.setdefault('pace', profile['pace'])
    base.setdefault('trip_type', profile['trip_type'])
    for key in ('route_days', 'destination_days', 'route_nights', 'destination_nights', 'total_days_source', 'stage_plan_mode'):
        base.setdefault(key, profile.get(key))
    return base


def decide_trip_type(trip_profile: dict[str, Any], route_context: dict[str, Any] | None = None) -> TripType:
    source = str(trip_profile.get('source_text') or '')
    origin = str(trip_profile.get('origin') or '')
    destination = str(trip_profile.get('destination') or '')
    mode = str(trip_profile.get('travel_mode') or 'driving')
    duration_days = int(trip_profile.get('duration_days') or 1)
    if any(keyword in source for keyword in ('附近', '周边', '周围')) and any(keyword in source for keyword in ('酒店', '餐厅', '景点')):
        return 'nearby_search'
    if any(keyword in source for keyword in ('上班', '通勤', '公司')):
        return 'commute'
    distance_meters = 0
    if route_context:
        try:
            distance_meters = int(route_context.get('route_total_distance_meters') or 0)
        except (TypeError, ValueError):
            distance_meters = 0
    explicit_along = any(keyword in source for keyword in ('沿途', '中途', '路上', '顺路'))
    cross_city = _looks_cross_city(origin, destination)
    far_enough = distance_meters >= 80_000 or cross_city
    if origin and destination and duration_days >= 2 and far_enough and (mode in {'driving', 'bicycling'} or explicit_along):
        return 'along_route_trip'
    return 'destination_trip'


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


_INDOOR_POI_KEYWORDS = ('博物馆', '美术馆', '纪念馆', '科技馆', '展览馆', '非遗馆', '室内', '体验馆', '商场')
_OUTDOOR_POI_KEYWORDS = ('公园', '湿地', '湖', '山', '步道', '古城墙', '广场', '森林', '自然风光', '峡谷', '登山', '徒步')


def score_poi(poi: dict[str, Any], trip_profile: dict[str, Any], route_context: dict[str, Any] | None = None) -> dict[str, float | str | list[str]]:
    name = str(poi.get('name') or poi.get('title') or '')
    category = str(poi.get('category') or '')
    address = str(poi.get('address') or '')
    combined = f'{name} {category} {address}'
    interest_tags = set(trip_profile.get('interest_tags') or [])
    avoid_tags = set(trip_profile.get('avoid_tags') or [])
    pace = str(trip_profile.get('pace') or 'normal')
    reasons: list[str] = []
    stage = str((route_context or {}).get('stage') or '')
    base_score = 20.0
    if _contains_any(combined, ('景区', '博物馆', '公园', '古城', '遗址', '纪念馆', '美术馆', '科技馆', '湿地', '乐园')):
        base_score += 15
    preference_score = 0.0
    tag_keywords = {
        '博物馆': ('博物馆', '纪念馆', '美术馆', '科技馆', '展览馆'),
        '公园': ('公园', '湿地', '湖', '步道', '绿道'),
        '古城': ('古城', '古镇', '城墙', '古迹'),
        '历史文化': ('历史', '文化', '遗址', '寺庙', '非遗', '文化街区'),
        '亲子': ('科技馆', '动物园', '乐园', '海洋馆', '体验馆'),
        '美食': ('小吃', '老字号', '夜市', '地方菜', '美食'),
        '自然风光': ('风景', '湖', '山', '湿地', '森林', '滨河'),
        '购物': ('商场', '购物', '商业街'),
        '夜景': ('夜景', '夜游', '灯光'),
        '老人友好': ('博物馆', '纪念馆', '公园', '室内', '文化'),
    }
    for tag, keywords in tag_keywords.items():
        if tag in interest_tags and _contains_any(combined, keywords):
            preference_score += 18
            reasons.append(f'{tag}偏好')
    route_score = 10.0
    if route_context and poi.get('route_order') is not None:
        route_score += 16 if stage == 'route' else 10
        reasons.append('顺路')
    time_fit_score = 10.0
    estimated_minutes = int(poi.get('estimated_minutes') or 120)
    available_minutes = int((route_context or {}).get('daily_available_visit_minutes') or 300)
    if estimated_minutes <= available_minutes:
        time_fit_score += 10
    elif estimated_minutes > available_minutes + 60:
        time_fit_score -= 8
    if stage == 'route' and estimated_minutes <= 120:
        time_fit_score += 8
        reasons.append('适合短暂停留')
    if stage == 'destination' and preference_score > 0:
        preference_score += 8
        reasons.append('目的地深度游')
    crowd_fit_score = 0.0
    if '亲子' in interest_tags and _contains_any(combined, ('科技馆', '动物园', '乐园', '海洋馆', '体验馆')):
        crowd_fit_score += 16
        reasons.append('亲子友好')
    if ('老人友好' in interest_tags or pace == 'relaxed') and _contains_any(combined, ('博物馆', '纪念馆', '美术馆', '公园', '文化')):
        crowd_fit_score += 12
        reasons.append('节奏友好')
    avoid_penalty = 0.0
    if '不爬山' in avoid_tags and _contains_any(combined, ('山', '登山', '徒步', '峡谷')):
        avoid_penalty += 28
        reasons.append('规避爬山')
    if '不逛商场' in avoid_tags and _contains_any(combined, ('商场', '购物中心', '商业')):
        avoid_penalty += 20
    if ('不太累' in avoid_tags or '少走路' in avoid_tags) and _contains_any(combined, ('山', '徒步', '步道', '长城')):
        avoid_penalty += 18
    must_visit_score = 0.0
    must_visit = bool(poi.get('must_visit')) or str(poi.get('must_visit')).lower() == 'true'
    if must_visit:
        must_visit_score += 60
        reasons.append('用户指定必去')
        if stage == 'route':
            reasons.append('途经点优先安排')
    weather_score = 0.0
    weather_day = (route_context or {}).get('weather_day') if isinstance(route_context, dict) else None
    if isinstance(weather_day, dict):
        indoor_priority = bool(weather_day.get('indoor_priority'))
        outdoor_suitability = str(weather_day.get('outdoor_suitability') or '')
        is_indoor = _contains_any(combined, _INDOOR_POI_KEYWORDS)
        is_outdoor = _contains_any(combined, _OUTDOOR_POI_KEYWORDS)
        if must_visit and is_outdoor and outdoor_suitability in {'poor', 'limited'}:
            weather_score += 18
            reasons.append('建议视天气调整时段或准备备选')
        if indoor_priority and is_indoor:
            weather_score += 22
            reasons.append('天气适配：雨天优先室内')
        if indoor_priority and is_outdoor:
            weather_score -= 18 if outdoor_suitability != 'poor' else 32
            reasons.append('天气适配：户外备选')
        if outdoor_suitability == 'good' and is_outdoor:
            weather_score += 12
            reasons.append('天气适合室外游览')
        if outdoor_suitability == 'poor' and is_outdoor:
            weather_score -= 16
            reasons.append('恶劣天气不建议户外')
    route_weight = 2.0 if stage == 'route' else 1.5
    preference_weight = 2.4 if stage == 'destination' else 2.0
    final_score = base_score + preference_score * preference_weight + route_score * route_weight + time_fit_score * 1.2 + crowd_fit_score + weather_score + must_visit_score - avoid_penalty * 2.0
    if not reasons:
        reasons.append('综合匹配')
    reason_prefix = '沿途阶段推荐' if stage == 'route' else '目的地深度游推荐' if stage == 'destination' else '优先推荐'
    return {
        'base_score': round(base_score, 2),
        'preference_score': round(preference_score, 2),
        'route_score': round(route_score, 2),
        'time_fit_score': round(time_fit_score, 2),
        'crowd_fit_score': round(crowd_fit_score, 2),
        'weather_score': round(weather_score, 2),
        'must_visit_score': round(must_visit_score, 2),
        'avoid_penalty': round(avoid_penalty, 2),
        'final_score': round(final_score, 2),
        'reason': f'{reason_prefix}：{"，".join(reasons[:4])}。',
        'tags': reasons[:4],
    }
