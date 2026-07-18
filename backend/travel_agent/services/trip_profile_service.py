from __future__ import annotations

import re
from typing import Any, Literal

from travel_agent.models.travel import TravelPlanRequest
from travel_agent.services.intent_service import extract_locations, extract_question_waypoints, extract_travel_mode, extract_trip_details
from travel_agent.services.location_text_service import strip_stopover_action_suffix

TripType = Literal['destination_trip', 'along_route_trip', 'commute', 'nearby_search', 'general_chat']

INTEREST_TAG_RULES: dict[str, tuple[str, ...]] = {
    '经典景点': ('经典景点', '经典', '地标', '必打卡'),
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


def _parse_stay_amount(num_text: str | None, unit_text: str | None = None) -> float | None:
    raw = (num_text or unit_text or '').strip()
    unit = (unit_text or '').strip()
    if raw in {'半', '半天'} or unit == '半天':
        return 0.5
    parsed = parse_cn_number(num_text)
    if parsed is not None:
        return float(parsed)
    if unit == '一晚':
        return 1.0
    return None


def _add_route_stop(
    stops: list[dict[str, Any]],
    name: str,
    *,
    destination: str | None,
    stop_type: str = 'city',
    stay_days: float | None = None,
    stay_nights: int | None = None,
    preferred_day: int | None = None,
    must_visit: bool = False,
    source: str = 'parsed_stopover',
) -> None:
    cleaned = strip_stopover_action_suffix(name.strip(' ，。；;、'))
    cleaned = re.sub(r'^(中途|途中|路上|沿途)?(?:在|到|去|途经|经过|路过)', '', cleaned)
    cleaned = strip_stopover_action_suffix(cleaned)
    cleaned = re.sub(r'(半天|一晚|\d+\s*[天晚]|[一二两三四五六七八九十]+\s*[天晚]).*$', '', cleaned).strip(' ，。；;、')
    if cleaned in {'中途', '途中', '路上', '沿途', '目的地', '剩余时间', '余下时间'}:
        return
    if not cleaned or len(cleaned) < 2:
        return
    destination_clean = (destination or '').replace('市', '').strip()
    if destination_clean and cleaned.replace('市', '').strip() == destination_clean:
        return
    existing = next((item for item in stops if item['name'] == cleaned), None)
    if existing:
        if stay_days is not None:
            existing['stay_days'] = max(float(existing.get('stay_days') or 0), stay_days)
        if stay_nights is not None:
            existing['stay_nights'] = max(int(existing.get('stay_nights') or 0), stay_nights)
        existing['must_visit'] = bool(existing.get('must_visit') or must_visit)
        if preferred_day and not existing.get('preferred_day'):
            existing['preferred_day'] = preferred_day
        return
    stops.append(
        {
            'name': cleaned,
            'type': stop_type,
            'stay_days': stay_days if stay_days is not None else 0,
            'stay_nights': stay_nights or 0,
            'preferred_day': preferred_day,
            'must_visit': must_visit,
            'source': source,
        }
    )


def parse_route_stops(text: str | None, *, destination: str | None = None) -> list[dict[str, Any]]:
    source = text or ''
    stops: list[dict[str, Any]] = []
    stopover_patterns = (
        r'(?:(?:中途|途中|路上|沿途)?在|途经|路过|经过)(?P<name>[^，。；,、和及]{2,12}?)(?:并且?|且)?(?P<action>停留|游玩|玩|住宿|住)(?P<num>半|\d+|[一二两三四五六七八九十]+)?\s*(?P<unit>半天|天|晚|一晚)?',
        r'(?P<name>[^，。；,、和及]{2,12}?)(?:并且?|且)?(?P<action>停留|游玩|玩|住宿|住)(?P<num>半|\d+|[一二两三四五六七八九十]+)?\s*(?P<unit>半天|天|晚|一晚)',
    )
    for pattern in stopover_patterns:
        for match in re.finditer(pattern, source):
            name = match.group('name')
            action = match.group('action') or ''
            unit = match.group('unit') or ''
            amount = _parse_stay_amount(match.group('num'), unit)
            stay_days = amount if unit in {'天', '半天'} or action in {'停留', '游玩', '玩'} else None
            stay_nights = int(amount or 1) if unit in {'晚', '一晚'} or action in {'住', '住宿'} else None
            if stay_days is None and stay_nights is not None:
                stay_days = float(max(1, stay_nights))
            _add_route_stop(
                stops,
                name,
                destination=destination,
                stay_days=stay_days,
                stay_nights=stay_nights,
                source='parsed_stopover',
            )
    for match in re.finditer(r'第(?P<num>\d+|[一二两三四五六七八九十]+)\s*[天日](?:到|抵达|住在|住)(?P<name>[^，。；,、和及]{2,12})', source):
        preferred_day = parse_cn_number(match.group('num'))
        _add_route_stop(stops, match.group('name'), destination=destination, stay_days=1, preferred_day=preferred_day, source='parsed_day_instruction')
    for item in extract_question_waypoints(source):
        _add_route_stop(stops, str(item.get('name') or ''), destination=destination, source='parsed_waypoint')
    for match in re.finditer(r'(?:沿途|途中|中途|路上)(?:必须|一定要|必去|必须去|一定要去)(?P<name>[^，。；,]+)', source):
        _add_route_stop(stops, match.group('name'), destination=destination, stop_type='attraction', must_visit=True, source='parsed_must_visit')
    return stops


def _parse_explicit_total_days(source: str) -> int | None:
    return _first_number_for_patterns(
        source,
        (
            r'(?:总共|一共|共|总计|全程|整体|总行程|总时长)\s*(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
            r'(?P<num>\d+|[一二两三四五六七八九十]+)\s*天(?:总共|一共|全程|总行程)',
        ),
    )


def _parse_explicit_duration(source: str) -> tuple[int | None, str | None]:
    explicit_total = _parse_explicit_total_days(source)
    if explicit_total is not None:
        return explicit_total, 'explicit_total'
    explicit_duration = _first_number_for_patterns(
        source,
        (
            r'(?P<num>\d+|[一二两三四五六七八九十]+)\s*[天日]\s*(?:\d+|[一二两三四五六七八九十]+)\s*晚',
            r'(?:行程时长|旅行时长|游玩时长|天数)\s*[：:]?\s*(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
        ),
    )
    return (explicit_duration, 'explicit_duration') if explicit_duration is not None else (None, None)


def parse_stage_days(text: str | None, *, destination: str | None = None) -> dict[str, int | None | str]:
    source = text or ''
    destination_clean = (destination or '').replace('市', '').strip()
    route_no_play = bool(re.search(r'(中途|路上|沿途|途中)(?:不|不用|不要|不安排)(?:玩|游玩|景点|停留)', source))
    destination_no_play = bool(re.search(r'(目的地|到达后|到了[^，。；,]*|到[^，。；,]{1,12})(?:不|不用|不要)(?:玩|游玩|停留)|到了就返程', source))
    route_days = 0 if route_no_play else _first_number_for_patterns(
        source,
        (
            r'(?:途中|路上|沿途|中途)(?:边走边玩|游玩|玩|安排|慢慢玩)?(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
            r'(?:途中|路上|沿途|中途).*?(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
        ),
    )
    destination_patterns = [
        r'(?:目的地|到目的地|目的地深度游)(?:游玩|玩|安排|深度游)?(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
    ]
    if destination_clean:
        escaped_destination = re.escape(destination_clean)
        destination_patterns.extend(
            (
                rf'(?:到了?|到|在)\s*{escaped_destination}(?:市)?(?:后|之后|后再|再)?(?:游玩|玩|安排|深度游|停留)(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
                rf'(?:到了?|到)\s*{escaped_destination}(?:市)?(?:后|之后|后再|再)(?P<num>\d+|[一二两三四五六七八九十]+)\s*天',
            )
        )
    destination_days = 0 if destination_no_play else _first_number_for_patterns(source, tuple(destination_patterns))
    route_nights = _first_number_for_patterns(
        source,
        (
            r'(?:路上|途中|沿途)(?:只)?(?:住|住宿)(?P<num>\d+|[一二两三四五六七八九十]+)\s*晚',
            r'(?:路上|途中|沿途).*?(?P<num>\d+|[一二两三四五六七八九十]+)\s*晚',
        ),
    )
    destination_night_patterns = [
        r'(?:目的地|到目的地)(?:住|住宿)(?P<num>\d+|[一二两三四五六七八九十]+)\s*晚',
    ]
    if destination_clean:
        escaped_destination = re.escape(destination_clean)
        destination_night_patterns.append(
            rf'(?:到了?|到|在)\s*{escaped_destination}(?:市)?(?:后|之后)?(?:住|住宿)(?P<num>\d+|[一二两三四五六七八九十]+)\s*晚'
        )
    destination_nights = _first_number_for_patterns(source, tuple(destination_night_patterns))
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


def _ceil_positive_days(value: float | int | None) -> int:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if amount <= 0:
        return 0
    whole = int(amount)
    return whole if amount == whole else whole + 1


def _wants_destination_remainder(source: str, destination: str | None) -> bool:
    destination_clean = (destination or '').replace('市', '').strip()
    if any(keyword in source for keyword in ('剩余时间', '剩下时间', '余下时间', '其余时间', '剩余的时间')):
        return True
    if destination_clean:
        return bool(re.search(rf'(?:到|在){re.escape(destination_clean)}(?:后|之后)?(?:游玩|玩|深度游|停留)', source))
    return False


def _route_days_from_stops(route_stops: list[dict[str, Any]], total_days: int | None) -> int | None:
    if not route_stops:
        return None
    full_stop_days = sum(max(1, _ceil_positive_days(stop.get('stay_days') or stop.get('stay_nights'))) for stop in route_stops if float(stop.get('stay_days') or 0) >= 1 or int(stop.get('stay_nights') or 0) >= 1)
    if full_stop_days:
        inferred = full_stop_days
    else:
        inferred = 1
    if total_days is not None and total_days > 1:
        return min(max(1, inferred), total_days)
    return max(1, inferred)


def build_trip_profile_from_text(text: str | None, *, origin: str | None = None, destination: str | None = None, travel_mode: str | None = None) -> dict[str, Any]:
    source = text or ''
    parsed_origin, parsed_destination = extract_locations(source)
    merged_origin = origin or parsed_origin
    merged_destination = destination or parsed_destination
    trip_details = extract_trip_details(source)
    mode = extract_travel_mode(source, travel_mode)
    explicit_total_days, duration_source = _parse_explicit_duration(source)
    duration_days = explicit_total_days or (int(trip_details['duration_days']) if trip_details.get('duration_days') else None)
    nights = int(trip_details['nights']) if trip_details.get('nights') else None
    stage_days = parse_stage_days(source, destination=merged_destination)
    route_days = stage_days.get('route_days')
    destination_days = stage_days.get('destination_days')
    route_stops = parse_route_stops(source, destination=merged_destination)
    wants_remainder = _wants_destination_remainder(source, merged_destination)
    stop_route_days = _route_days_from_stops(route_stops, duration_days)
    if stop_route_days is not None:
        route_days = max(int(route_days), stop_route_days) if isinstance(route_days, int) else stop_route_days
    if wants_remainder and destination_days is None and duration_days is not None and isinstance(route_days, int):
        if duration_days - route_days <= 0 and duration_days > 1:
            route_days = duration_days - 1
        destination_days = max(1, duration_days - int(route_days))
    if isinstance(route_days, int) and isinstance(destination_days, int):
        stage_sum = route_days + destination_days
        if explicit_total_days is not None:
            duration_days = explicit_total_days
            total_days_source = str(duration_source or 'explicit_duration')
        else:
            duration_days = stage_sum
            total_days_source = 'stage_sum'
    else:
        total_days_source = str(duration_source or (stage_days.get('total_days_source') if duration_days is None else 'inferred') or 'inferred')
        if duration_days is None and isinstance(route_days, int):
            duration_days = route_days
        if duration_days is None and isinstance(destination_days, int):
            duration_days = destination_days
    if duration_days is None and nights is not None:
        duration_days = nights + 1
        duration_source = 'nights_inferred'
        total_days_source = 'nights_inferred'
    if duration_days is None:
        duration_days = 2 if any(keyword in source for keyword in ('周末', '两天', '二天')) else 3
        duration_source = 'default'
        total_days_source = 'default'
    if wants_remainder and destination_days is None and isinstance(route_days, int):
        if duration_days - route_days <= 0 and duration_days > 1:
            route_days = duration_days - 1
        destination_days = max(1, duration_days - int(route_days))
    if isinstance(route_days, int) and destination_days is None and route_days < duration_days and wants_remainder:
        destination_days = duration_days - route_days
    buffer_days = max(0, int(duration_days or 0) - int(route_days or 0) - int(destination_days or 0))
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
        'budget': None,
        'waypoints': extract_question_waypoints(source),
        'interest_tags': interest_tags,
        'avoid_tags': avoid_tags,
        'pace': pace,
        'trip_type': trip_type,
        'route_days': route_days,
        'destination_days': destination_days,
        'buffer_days': buffer_days,
        'route_nights': stage_days.get('route_nights'),
        'destination_nights': stage_days.get('destination_nights'),
        'route_stops': route_stops,
        'destination_stay_days': destination_days,
        'total_days_source': total_days_source,
        'duration_source': duration_source or ('stage_sum' if total_days_source == 'stage_sum' else 'inferred'),
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
    for key in ('route_days', 'destination_days', 'buffer_days', 'route_nights', 'destination_nights', 'route_stops', 'destination_stay_days', 'total_days_source', 'duration_source', 'stage_plan_mode', 'explicit_total_days'):
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
