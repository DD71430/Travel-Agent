from __future__ import annotations

from collections import defaultdict, deque
from typing import Any
from uuid import uuid4

import httpx
import re

from travel_agent.core.config import get_settings
from travel_agent.models.travel import (
    ConversationTurn,
    RouteOption,
    RouteStep,
    TripDayPlan,
    TravelPlanRequest,
    TravelPlanResponse,
)
from travel_agent.tools.tencent_webservice_client import TencentWebServiceClient, TencentWebServiceError

settings = get_settings()
_history_store: dict[str, deque[ConversationTurn]] = defaultdict(lambda: deque(maxlen=10))
_preference_store: dict[str, list[str]] = defaultdict(list)
_client = TencentWebServiceClient()


class TencentMapsError(RuntimeError):
    pass


TENCENT_ROUTE_ENDPOINTS = {
    'driving': '/ws/direction/v1/driving',
    'walking': '/ws/direction/v1/walking',
    'transit': '/ws/direction/v1/transit',
    'bicycling': '/ws/direction/v1/bicycling',
}

_ATTRACTION_KEYWORDS = ['景点', '公园', '博物馆', '风景区', '旅游景区', '名胜古迹', '文化街区', '古城', '古镇', '寺庙', '湖泊']
_HOTEL_KEYWORDS = ['酒店', '宾馆', '度假酒店']
_FOOD_KEYWORDS = ['本地特色餐', '老字号', '小吃', '夜市', '地方菜']
_CITY_HINTS = ('北京', '上海', '广州', '深圳', '杭州', '济南', '南京', '苏州', '成都', '重庆', '武汉', '西安', '天津', '青岛', '厦门', '长沙', '郑州', '合肥', '福州', '昆明', '哈尔滨', '大连', '宁波', '无锡', '佛山', '东莞', '烟台', '珠海', '南昌', '徐州', '泰安', '德州', '曲阜')
_INDOOR_HINTS = ('博物馆', '美术馆', '展览馆', '科技馆', '书店', '非遗', '商场', '纪念馆', '体验馆', '剧院')
_OUTDOOR_HINTS = ('公园', '湖', '塔', '山', '古镇', '步道', '湿地', '乐园', '街区', '岛', '滨河', '古城', '城墙')

_ATTRACTION_DURATION_RULES: list[tuple[tuple[str, ...], tuple[int, int], str]] = [
    (('博物馆', '纪念馆', '美术馆', '科技馆', '展览馆', '非遗馆'), (150, 180), '适合预留完整展线参观时间'),
    (('古城', '古镇', '历史文化街区', '城墙', '遗址', '古迹'), (120, 150), '适合按主游览线分段步行游览'),
    (('公园', '湖', '湿地', '山', '步道', '滨河'), (90, 120), '适合控制为半日慢游'),
    (('寺', '塔', '教堂', '书院'), (60, 90), '适合与周边景点串联安排'),
    (('乐园', '动物园', '植物园', '海洋馆'), (180, 240), '适合预留较长体验时间'),
    (('地标', '观景台', '广场'), (45, 60), '适合作为短时打卡或傍晚收尾点'),
]


def _classify_intent(text: str) -> str:
    keywords = ('路线', '出行', '旅行', '怎么去', '规划', '回家', '上班', '通勤')
    return 'travel_planning' if any(keyword in text for keyword in keywords) else 'general_chat'



def _classify_scenario(request: TravelPlanRequest) -> str:
    combined = f"{request.origin}{request.destination}{request.preferences or ''}{request.source_query or ''}"
    if any(word in combined for word in ('上班', '通勤', '公司', '地铁')):
        return 'daily_commute'
    if any(word in combined for word in ('旅游', '景区', '酒店', '周末', '度假', '几天', '天游', '行程')):
        return 'travel_tourism'
    return 'general_trip'



def _extract_preferences(request: TravelPlanRequest) -> list[str]:
    prefs = []
    for text in (request.preferences, request.source_query):
        if text:
            prefs.extend([item.strip() for item in re.split(r'[，,；;、\n]', text) if item.strip()])
    if request.travel_mode == 'transit':
        prefs.append('优先公共交通')
    if request.travel_mode == 'driving':
        prefs.append('优先驾车出行')
    return prefs or ['无显式偏好']



def _parse_distance(distance_meters: Any) -> str:
    try:
        meters = float(distance_meters)
    except (TypeError, ValueError):
        return '未知距离'
    if meters >= 1000:
        return f'{meters / 1000:.1f}km'
    return f'{int(meters)}m'



def _parse_duration(duration_minutes: Any) -> str:
    try:
        minutes = float(duration_minutes)
    except (TypeError, ValueError):
        return '未知时长'
    return f'{max(1, round(minutes))}分钟'



def _normalize_route_steps(route: dict[str, Any]) -> list[RouteStep]:
    steps: list[RouteStep] = []
    for item in route.get('steps', []):
        if not isinstance(item, dict):
            continue
        steps.append(
            RouteStep(
                instruction=str(item.get('instruction') or item.get('act_desc') or '继续前进'),
                distance=_parse_distance(item.get('distance')) if item.get('distance') is not None else None,
                duration=_parse_duration(item.get('duration')) if item.get('duration') is not None else None,
                road_name=item.get('road_name') or item.get('road_name_desc'),
                direction=item.get('dir_desc'),
                action=item.get('act_desc'),
            )
        )
    return steps



def _build_route_option_from_route(route: dict[str, Any], title: str, reasons: list[str], waypoint_summary: str | None = None) -> RouteOption:
    distance = _parse_distance(route.get('distance'))
    duration = _parse_duration(route.get('duration'))
    steps = _normalize_route_steps(route)
    tags = route.get('tags') or []
    if not steps:
        steps = [RouteStep(instruction='从起点前往目的地')]
    return RouteOption(
        title=title,
        summary=f'{title}，整体耗时约{duration}，距离约{distance}。',
        distance=distance,
        duration=duration,
        reasons=reasons,
        steps=steps,
        mode=route.get('mode'),
        tags=[str(tag) for tag in tags if tag],
        toll=route.get('toll'),
        traffic_light_count=route.get('traffic_light_count'),
        waypoint_summary=waypoint_summary,
    )



def _looks_like_coordinate(value: str) -> bool:
    parts = value.split(',')
    if len(parts) != 2:
        return False
    try:
        float(parts[0].strip())
        float(parts[1].strip())
        return True
    except ValueError:
        return False



def _looks_like_poi(text: str | None) -> bool:
    if not text:
        return False
    cleaned = text.strip().replace(' ', '')
    poi_keywords = ('景区', '公园', '园', '馆', '宫', '湖', '山', '寺', '庙', '桥', '塔', '院', '站', '场', '路', '街', '里', '村')
    region_suffixes = ('市', '省', '自治区', '特别行政区', '区', '县')
    if any(cleaned.endswith(suffix) for suffix in region_suffixes):
        return False
    return any(keyword in cleaned for keyword in poi_keywords)



def _normalize_region(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip().replace(' ', '')
    replacements = {
        '北京市': '北京',
        '上海市': '上海',
        '天津市': '天津',
        '重庆市': '重庆',
    }
    if cleaned in replacements:
        return replacements[cleaned]
    inferred = _client._infer_region(cleaned)
    if inferred:
        return inferred
    if _looks_like_poi(cleaned):
        return None
    return cleaned



def _infer_region_from_text(text: str | None) -> str | None:
    return _normalize_region(text)



def _extract_place_location(data: dict[str, Any]) -> str | None:
    records = data.get('data') or []
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        return None
    for item in records:
        if not isinstance(item, dict):
            continue
        location = item.get('location') or {}
        lat = location.get('lat')
        lng = location.get('lng')
        if lat is None or lng is None:
            continue
        return f'{lat},{lng}'
    return None



def _suggestion_search_address(keyword: str, region: str | None = None) -> str | None:
    if not settings.tencent_maps_key:
        return None
    normalized_region = _normalize_region(region)
    try:
        data = _client.suggestion(keyword, region=normalized_region)
    except TencentWebServiceError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get('status') not in (0, '0'):
        return None
    records = data.get('data') or []
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        return None
    for item in records:
        if not isinstance(item, dict):
            continue
        location = item.get('location') or {}
        lat = location.get('lat')
        lng = location.get('lng')
        if lat is None or lng is None:
            continue
        return f'{lat},{lng}'
    return None



def _place_search_address(keyword: str, region: str | None = None) -> str | None:
    if not settings.tencent_maps_key:
        return None
    boundary_region = _normalize_region(region) or '北京'
    try:
        data = _client.place_search(keyword, boundary=f'region({boundary_region},0)')
    except TencentWebServiceError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get('status') not in (0, '0'):
        return None
    location = _extract_place_location(data)
    return location



def _resolve_location_point(address: str, region: str | None = None) -> tuple[str | None, str]:
    if _looks_like_coordinate(address):
        return address, 'coordinate'

    cleaned_address = _client._clean_address(address)
    region_hint = _normalize_region(region)
    inferred_region = region_hint or _normalize_region(cleaned_address) or '北京'

    if _looks_like_poi(cleaned_address):
        poi_location = _place_search_address(cleaned_address, inferred_region)
        if poi_location:
            return poi_location, 'place_search'
        suggestion_location = _suggestion_search_address(cleaned_address, inferred_region)
        if suggestion_location:
            return suggestion_location, 'suggestion'

    url = f"{settings.tencent_maps_base_url.rstrip('/')}/ws/geocoder/v1"
    params = {
        'key': settings.tencent_maps_key,
        'address': cleaned_address,
        'region': inferred_region,
        'output': 'json',
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPStatusError, httpx.HTTPError, ValueError):
        data = None

    if isinstance(data, dict) and data.get('status') in (0, '0'):
        result = data.get('result') or {}
        location = result.get('location') or {}
        lat = location.get('lat')
        lng = location.get('lng')
        if lat is not None and lng is not None:
            return f'{lat},{lng}', 'geocoder'

    fallback_place = _place_search_address(cleaned_address, inferred_region)
    if fallback_place:
        return fallback_place, 'place_search_fallback'

    fallback_suggestion = _suggestion_search_address(cleaned_address, inferred_region)
    if fallback_suggestion:
        return fallback_suggestion, 'suggestion_fallback'

    return _fallback_region_coordinates(inferred_region), 'region_center'



def _fallback_region_coordinates(region: str) -> str | None:
    centers = {
        '北京': '39.9042,116.4074',
        '上海': '31.2304,121.4737',
        '天津': '39.3434,117.3616',
        '重庆': '29.5630,106.5516',
        '山东省': '36.6512,117.1201',
        '浙江省': '30.2741,120.1551',
        '济南': '36.6512,117.1201',
        '南京': '32.0603,118.7969',
        '杭州': '30.2741,120.1551',
    }
    normalized = _normalize_region(region)
    if normalized in centers:
        return centers[normalized]
    if normalized and normalized.endswith('市'):
        return centers.get(normalized[:-1])
    return None



def _geocode_address(address: str, region: str | None = None) -> str:
    if not settings.tencent_maps_key:
        raise TencentMapsError('Tencent Maps key is not configured')

    location, source = _resolve_location_point(address, region)
    if location:
        return location
    raise TencentMapsError(f'Unable to resolve location for {address} via {source}')



def _fallback_routes(request: TravelPlanRequest, scenario: str, reason: str = 'fallback') -> list[RouteOption]:
    provider_note = f'腾讯地图兜底方案({reason})'
    waypoint_summary = '；'.join(w.name for w in request.waypoints) if request.waypoints else None
    base_steps = [
        {'instruction': f'从{request.origin}出发', 'distance': 1000, 'duration': 4, 'road_name': '', 'dir_desc': '北', 'act_desc': '直行'},
        {'instruction': '沿主路前进', 'distance': 1500, 'duration': 12, 'road_name': '主路', 'dir_desc': '东', 'act_desc': '直行'},
        {'instruction': f'到达{request.destination}', 'distance': 700, 'duration': 8, 'road_name': '', 'dir_desc': '', 'act_desc': ''},
    ]
    if request.travel_mode == 'transit':
        return [
            _build_route_option_from_route(
                {'distance': 15800, 'duration': 34, 'steps': base_steps, 'mode': 'TRANSIT', 'tags': ['少换乘']},
                f'{provider_note}公交方案',
                ['兜底数据', '未获取到真实公交路线', '仅用于页面演示'],
                waypoint_summary,
            )
        ]
    return [
        _build_route_option_from_route(
            {'distance': 12400, 'duration': 28, 'steps': base_steps, 'mode': 'DRIVING', 'tags': ['RECOMMEND'], 'toll': 0, 'traffic_light_count': 8},
            f'{provider_note}默认方案',
            ['兜底数据', '未获取到真实路线', '仅用于页面演示'],
            waypoint_summary,
        )
    ]



def _route_quality_label(distance_text: str, duration_text: str, request: TravelPlanRequest) -> str:
    if '未知' in distance_text or '未知' in duration_text:
        return 'low'
    if request.travel_mode == 'driving' and distance_text.endswith('km'):
        try:
            dist = float(distance_text[:-2])
            if dist > 500:
                return 'low'
        except ValueError:
            return 'low'
    return 'high'



def _sort_waypoints(request: TravelPlanRequest) -> list[str]:
    names = [w.name.strip() for w in request.waypoints if w.name.strip()]
    if not request.waypoint_order or len(names) <= 1:
        return names
    return sorted(names, key=len)



def _fetch_tencent_route_options(request: TravelPlanRequest, scenario: str) -> tuple[list[RouteOption], str, str | None, dict[str, str]]:
    if not settings.tencent_maps_key:
        return _fallback_routes(request, scenario, 'missing_key'), 'fallback', 'Tencent Maps key is not configured', {'reason': 'missing_key'}

    endpoint = TENCENT_ROUTE_ENDPOINTS.get(request.travel_mode)
    if not endpoint:
        return _fallback_routes(request, scenario, 'unsupported_mode'), 'fallback', f'Unsupported travel mode: {request.travel_mode}', {'reason': 'unsupported_mode'}

    waypoint_names = _sort_waypoints(request)
    waypoint_coords: list[str] = []
    location_debug: dict[str, str] = {}
    try:
        origin_region = _infer_region_from_text(request.origin)
        destination_region = _infer_region_from_text(request.destination) or origin_region
        origin_point, origin_source = _resolve_location_point(request.origin, region=origin_region)
        destination_point, destination_source = _resolve_location_point(request.destination, region=destination_region)
        location_debug['origin_source'] = origin_source
        location_debug['destination_source'] = destination_source
        if not origin_point:
            raise TencentMapsError(f'Unable to resolve origin: {request.origin} via {origin_source}')
        if not destination_point:
            raise TencentMapsError(f'Unable to resolve destination: {request.destination} via {destination_source}')
        location_debug['origin_point'] = origin_point
        location_debug['destination_point'] = destination_point
        for waypoint in waypoint_names:
            waypoint_point, waypoint_source = _resolve_location_point(waypoint, region=_infer_region_from_text(waypoint) or origin_region)
            if not waypoint_point:
                raise TencentMapsError(f'Unable to resolve waypoint: {waypoint} via {waypoint_source}')
            waypoint_coords.append(waypoint_point)
            location_debug[f'waypoint:{waypoint}'] = waypoint_source
    except TencentMapsError as exc:
        location_debug['reason'] = 'geocode_failed'
        return _fallback_routes(request, scenario, 'geocode_failed'), 'fallback', f'Geocode failed: {exc}', location_debug

    url = f"{settings.tencent_maps_base_url.rstrip('/')}{endpoint}"
    params: dict[str, Any] = {
        'key': settings.tencent_maps_key,
        'from': origin_point,
        'to': destination_point,
        'output': 'json',
    }
    if waypoint_coords:
        params['waypoints'] = ';'.join(waypoint_coords)
    if request.travel_mode == 'driving':
        params['policy'] = 'LEAST_TIME'
        params['get_mp'] = '1'
        params['get_speed'] = '1'
        if request.waypoint_order and waypoint_coords:
            params['waypoint_order'] = '1'
    elif request.travel_mode == 'transit':
        params['policy'] = 'LEAST_TIME'

    try:
        with httpx.Client(timeout=12.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        location_debug['reason'] = 'http_error'
        return _fallback_routes(request, scenario, 'http_error'), 'fallback', f'HTTP error: {exc.response.status_code}', location_debug
    except (httpx.HTTPError, ValueError) as exc:
        location_debug['reason'] = 'request_failed'
        return _fallback_routes(request, scenario, 'request_failed'), 'fallback', f'Request failed: {exc}', location_debug

    if not isinstance(data, dict):
        location_debug['reason'] = 'invalid_payload'
        return _fallback_routes(request, scenario, 'invalid_payload'), 'fallback', 'Route API returned invalid payload', location_debug

    if data.get('status') not in (0, '0'):
        location_debug['reason'] = 'api_error'
        return _fallback_routes(request, scenario, 'api_error'), 'fallback', f"API error: {data.get('message', 'unknown error')}", location_debug

    result = data.get('result') or {}
    routes = result.get('routes') or []
    if isinstance(routes, dict):
        routes = [routes]
    if not routes:
        location_debug['reason'] = 'empty_routes'
        return _fallback_routes(request, scenario, 'empty_routes'), 'fallback', 'Route API returned no routes', location_debug

    waypoint_summary = '；'.join(waypoint_names) if waypoint_names else None
    options: list[RouteOption] = []
    for index, route in enumerate(routes[:3], start=1):
        if not isinstance(route, dict):
            continue
        options.append(
            _build_route_option_from_route(
                route,
                f'腾讯地图方案{index}',
                ['腾讯地图真实返回', '按接口结果结构化生成', '适合作为规划候选方案'],
                waypoint_summary,
            )
        )

    if not options:
        location_debug['reason'] = 'no_valid_routes'
        return _fallback_routes(request, scenario, 'no_valid_routes'), 'fallback', 'No valid route data', location_debug
    location_debug['reason'] = 'success'
    return options, 'tencent_maps', None, location_debug



def _choose_best_option(options: list[RouteOption], request: TravelPlanRequest) -> RouteOption:
    if request.preferences and '少换乘' in request.preferences and len(options) > 1:
        return options[0]
    return options[0]



def _get_route_numeric_value(text: str) -> float | None:
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None



def _validate_route_reasonableness(best_option: RouteOption, request: TravelPlanRequest) -> list[str]:
    issues: list[str] = []
    distance_value = _get_route_numeric_value(best_option.distance)
    duration_value = _get_route_numeric_value(best_option.duration)
    if distance_value is None or duration_value is None:
        return issues
    if request.origin.strip() == request.destination.strip():
        issues.append('出发地和目的地相同')
    if distance_value <= 1 and request.origin.strip() != request.destination.strip():
        issues.append('距离异常过短')
    if duration_value <= 1 and request.origin.strip() != request.destination.strip():
        issues.append('耗时异常过短')
    if distance_value > 5000 and duration_value <= 5:
        issues.append('距离与耗时不匹配')
    if request.travel_mode == 'driving' and distance_value < 5 and duration_value < 5:
        issues.append('驾车路线过短，可能是错误地理编码')
    return issues



def _extract_trip_profile(request: TravelPlanRequest) -> dict[str, Any]:
    source_text = request.source_query or ''
    text = source_text.strip()
    duration_match = re.search(r'(\d+)\s*天', text)
    budget_match = re.search(r'(\d+)\s*元', text)
    nights_match = re.search(r'(\d+)\s*晚', text)
    budget = budget_match.group(1) if budget_match else None
    days = int(duration_match.group(1)) if duration_match else None
    nights = int(nights_match.group(1)) if nights_match else None
    if days is None and nights is not None:
        days = nights + 1
    if days is None:
        if any(word in text for word in ('周末', '双休日')):
            days = 2
        elif any(word in text for word in ('3天', '三天')):
            days = 3
        elif any(word in text for word in ('4天', '四天')):
            days = 4
        else:
            days = 3
    if not budget:
        if '5000' in text:
            budget = '5000'
        elif '3000' in text:
            budget = '3000'
    base_profile = request.trip_profile or {}
    travel_style = str(base_profile.get('travel_style') or ('轻松慢游' if any(word in text for word in ('轻松', '慢游', '休闲', '不赶')) else '常规游玩'))
    companions = str(base_profile.get('companions') or ('家庭/朋友' if any(word in text for word in ('家人', '家庭', '朋友', '亲子')) else '默认'))
    return {
        'duration_days': int(base_profile.get('duration_days') or days),
        'budget': base_profile.get('budget') or budget,
        'travel_style': travel_style,
        'companions': companions,
    }




def _extract_weather_summary(payload: dict[str, Any]) -> str | None:
    result = payload.get('result') if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return None
    ad_info = result.get('ad_info') or {}
    city_name = ad_info.get('name') or ''
    forecasts = result.get('forecast') or result.get('forecasts') or []
    if isinstance(forecasts, dict):
        forecasts = [forecasts]
    if isinstance(forecasts, list) and forecasts:
        first = forecasts[0] if isinstance(forecasts[0], dict) else {}
        weather = first.get('weather') or first.get('day_weather') or first.get('night_weather') or '天气未知'
        temp = first.get('max_degree') or first.get('max_temperature') or first.get('degree') or '--'
        min_temp = first.get('min_degree') or first.get('min_temperature')
        wind = first.get('wind_direction') or first.get('wind_power') or ''
        temp_text = f'{min_temp}~{temp}°C' if min_temp not in (None, '') and temp not in (None, '') else f'{temp}°C'
        return f'{city_name}近期天气：{weather}，温度约 {temp_text}，{wind}'.strip('，')
    now = result.get('realtime') or result.get('now') or {}
    if isinstance(now, dict) and now:
        weather = now.get('weather') or now.get('info') or '天气未知'
        temp = now.get('temperature') or now.get('degree') or '--'
        return f'{city_name}当前天气：{weather}，温度约 {temp}°C'
    return None



def _fetch_weather_hint(destination: str, destination_point: str | None) -> str:
    if not settings.tencent_maps_key or not destination_point:
        return f'建议出行前查看{destination}未来 7 天天气，优先避开连续降雨或高温天气。'
    try:
        reverse = _client.reverse_geocoder(destination_point)
        result = reverse.get('result') if isinstance(reverse, dict) else {}
        ad_info = result.get('ad_info') if isinstance(result, dict) else {}
        adcode = ad_info.get('adcode') if isinstance(ad_info, dict) else None
        if adcode:
            weather_payload = _client.weather_info(str(adcode))
            weather_summary = _extract_weather_summary(weather_payload)
            if weather_summary:
                return weather_summary
    except TencentWebServiceError:
        pass
    return f'建议出行前查看{destination}未来 7 天天气，优先避开连续降雨或高温天气。'



def _is_relevant_address(address: str | None, region_hint: str | None) -> bool:
    if not address:
        return True
    if not region_hint:
        return True
    normalized_region = _normalize_region(region_hint) or region_hint
    if normalized_region in {'目标城市', '未知城市', '默认城市'}:
        return True
    compact_address = address.replace(' ', '')
    normalized_candidates = {normalized_region}
    if normalized_region.endswith('市'):
        normalized_candidates.add(normalized_region[:-1])
    else:
        normalized_candidates.add(f'{normalized_region}市')
    return any(candidate and candidate in compact_address for candidate in normalized_candidates)



def _extract_places(payload: dict[str, Any], region_hint: str | None = None) -> list[str]:
    data = payload.get('data') or payload.get('result') or []
    if isinstance(data, dict):
        data = [data]
    names: list[str] = []
    if not isinstance(data, list):
        return names
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get('title') or item.get('name') or item.get('address')
        address = item.get('address') or item.get('ad_info', {}).get('name')
        if address and not _is_relevant_address(str(address), region_hint):
            continue
        if name and address:
            names.append(f'{name}（{address}）')
        elif name:
            names.append(str(name))
    return names



def _fetch_along_route_attractions(origin_point: str | None, destination_point: str | None, region_hint: str | None) -> list[str]:
    if not settings.tencent_maps_key or not origin_point or not destination_point:
        return []
    collected: list[str] = []
    for keyword in _ATTRACTION_KEYWORDS:
        try:
            payload = _client.alongby(keyword, origin_point, destination_point, radius=3000)
            collected.extend(_extract_places(payload, region_hint))
        except TencentWebServiceError:
            continue
    deduped: list[str] = []
    for item in collected:
        if item not in deduped:
            deduped.append(item)
    if deduped:
        return deduped[:6]
    if region_hint:
        return [f'{region_hint}沿线可重点关注城市地标、公园和博物馆类景点']
    return []



def _extract_poi_candidates(payload: dict[str, Any], region_hint: str | None = None) -> list[dict[str, str]]:
    results = payload.get('data') or payload.get('result') or []
    if isinstance(results, dict):
        results = [results]
    candidates: list[dict[str, str]] = []
    if not isinstance(results, list):
        return candidates
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or item.get('name') or '').strip()
        if not title:
            continue
        address = str(item.get('address') or '').strip()
        if address and not _is_relevant_address(address, region_hint):
            continue
        category = str(item.get('category') or '').strip()
        location = item.get('location') if isinstance(item.get('location'), dict) else {}
        lat = location.get('lat')
        lng = location.get('lng')
        coords = f'{lat},{lng}' if lat is not None and lng is not None else ''
        candidates.append({
            'name': title,
            'address': address,
            'category': category,
            'location': coords,
        })
    return candidates



def _search_hotels_for_city(city: str, center_point: str | None = None) -> list[dict[str, str]]:
    if not settings.tencent_maps_key:
        return []
    collected: list[dict[str, str]] = []
    for keyword in _HOTEL_KEYWORDS:
        try:
            payload = _client.place_search_by_region(keyword, city, page_size=5, page_index=1)
            collected.extend(_extract_poi_candidates(payload, city))
        except TencentWebServiceError:
            continue
    if center_point:
        for keyword in ('酒店', '宾馆'):
            try:
                payload = _client.place_search_nearby_sorted(keyword, center_point, radius=2500, page_size=5, page_index=1)
                collected.extend(_extract_poi_candidates(payload, city))
            except TencentWebServiceError:
                continue
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in collected:
        key = f"{item['name']}|{item['address']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:6]



def _search_foods_for_location(city: str, center_point: str | None = None) -> list[dict[str, str]]:
    if not settings.tencent_maps_key:
        return []
    collected: list[dict[str, str]] = []
    if center_point:
        for keyword in _FOOD_KEYWORDS:
            try:
                payload = _client.place_search_nearby_sorted(keyword, center_point, radius=1800, page_size=6, page_index=1)
                collected.extend(_extract_poi_candidates(payload, city))
            except TencentWebServiceError:
                continue
    else:
        for keyword in _FOOD_KEYWORDS:
            try:
                payload = _client.place_search_by_region(keyword, city, page_size=6, page_index=1)
                collected.extend(_extract_poi_candidates(payload, city))
            except TencentWebServiceError:
                continue
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in collected:
        key = f"{item['name']}|{item['address']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:8]



def _build_transportation_suggestions(request: TravelPlanRequest, best_option: RouteOption) -> list[str]:
    distance_value = _get_route_numeric_value(best_option.distance) or 0
    duration_value = _get_route_numeric_value(best_option.duration) or 0
    suggestions: list[str] = []
    mode_labels = {
        'driving': '驾车',
        'walking': '步行',
        'transit': '公共交通',
        'bicycling': '骑行',
    }
    suggestions.append(f'当前推荐以{mode_labels.get(request.travel_mode, request.travel_mode)}为主，预计 {best_option.duration} / {best_option.distance}。')
    if request.travel_mode == 'driving':
        if distance_value >= 200:
            suggestions.append('路程较长，建议中途安排服务区休息，并提前确认高速费与拥堵情况。')
        else:
            suggestions.append('驾车路程适中，建议避开早晚高峰，优先使用导航实时躲避拥堵。')
        if best_option.traffic_light_count:
            suggestions.append(f'沿途预计经过约 {best_option.traffic_light_count} 个红绿灯，注意预留缓冲时间。')
    elif request.travel_mode == 'transit':
        suggestions.append('公共交通方案更适合控制成本，建议优先查看首末班时间与换乘衔接。')
    elif request.travel_mode == 'walking':
        suggestions.append('步行方案适合短途游览，建议穿舒适鞋并留意天气变化。')
    elif request.travel_mode == 'bicycling':
        suggestions.append('骑行方案适合城市近距离串联景点，注意补水与骑行安全。')
    if duration_value >= 180:
        suggestions.append('总耗时较长，可考虑拆分为去程、游玩、返程三个阶段安排。')
    return suggestions[:4]



def _build_summary(
    request: TravelPlanRequest,
    option: RouteOption,
    scenario: str,
    data_source: str,
    quality_note: str | None = None,
    weather_hint: str | None = None,
    attraction_recommendations: list[str] | None = None,
    hotel_candidates: list[dict[str, str]] | None = None,
    food_candidates: list[dict[str, str]] | None = None,
) -> str:
    preference_text = request.preferences or '没有额外偏好'
    waypoint_text = '、'.join(w.name for w in request.waypoints) if request.waypoints else '无途经点'
    profile = _extract_trip_profile(request)
    mode_labels = {
        'driving': '自驾',
        'walking': '步行',
        'transit': '公共交通',
        'bicycling': '骑行',
    }
    hotel_preview = '；'.join(
        f"{item.get('name')}{f'（{item.get('address')}）' if item.get('address') else ''}"
        for item in (hotel_candidates or [])[:2]
        if item.get('name')
    )
    food_preview = '；'.join(
        f"{item.get('name')}{f'（{item.get('address')}）' if item.get('address') else ''}"
        for item in (food_candidates or [])[:3]
        if item.get('name')
    )
    summary_lines = [
        f'{request.origin}到{request.destination}{profile["duration_days"]}天旅游规划',
        f'建议以{mode_labels.get(request.travel_mode, request.travel_mode)}为主，整体通行时间约{option.duration}，适合作为这次行程的交通骨架。',
        f'旅行风格为{profile["travel_style"]}，重点关注景点串联与路程衔接。',
        f'途经安排：{waypoint_text}。',
        f'规划侧重点：{preference_text}',
    ]
    if weather_hint:
        summary_lines.append(f'天气参考：{weather_hint}')
        if any(keyword in weather_hint for keyword in ('雨', '阵雨', '雷')):
            summary_lines.append('天气策略：优先安排博物馆、室内街区、商业综合体等室内项目，室外步行段压缩到早晚。')
        elif any(keyword in weather_hint for keyword in ('高温', '暴晒')):
            summary_lines.append('天气策略：中午避开户外暴晒时段，优先上午/傍晚游湖滨、公园和步道。')
    if attraction_recommendations:
        summary_lines.append(f'推荐游玩方向：{"；".join(attraction_recommendations[:4])}')
    if hotel_preview:
        summary_lines.append(f'住宿参考：{hotel_preview}')
    if food_preview:
        summary_lines.append(f'餐饮参考：{food_preview}')
    if option.reasons:
        summary_lines.append(f'交通方案说明：{"；".join(option.reasons[:2])}')
    if quality_note:
        summary_lines.append(f'补充提示：{quality_note}')
    summary_lines.append(f'数据来源：{data_source}，场景判断：{scenario}')
    return '\n'.join(summary_lines)



def _extract_requested_foods(text: str | None) -> list[str]:
    source = text or ''
    foods = ['烤鸭', '涮肉', '炸酱面', '豆汁', '卤煮', '小吃', '火锅', '烧烤', '鲁菜', '川菜', '粤菜', '素食']
    return [food for food in foods if food in source]



def _clean_attraction_name(value: str) -> str:
    cleaned = re.sub(r'（.*?）', '', value).strip()
    cleaned = cleaned.split('（', 1)[0].strip()
    cleaned = re.sub(r'^(景点|推荐|建议|可去|值得去)[:：\s]*', '', cleaned).strip()
    return cleaned or value



def _pick_daily_spots(attraction_pool: list[str], day_index: int, weather_hint: str) -> tuple[str, str, str]:
    indoor = [item for item in attraction_pool if any(keyword in item for keyword in _INDOOR_HINTS)]
    outdoor = [item for item in attraction_pool if any(keyword in item for keyword in _OUTDOOR_HINTS)]
    neutral = [item for item in attraction_pool if item not in indoor and item not in outdoor]
    needs_indoor_priority = any(keyword in weather_hint for keyword in ('雨', '阵雨', '雷'))
    needs_heat_avoidance = any(keyword in weather_hint for keyword in ('高温', '暴晒'))
    if needs_indoor_priority:
        ordered = indoor + neutral + outdoor
    elif needs_heat_avoidance:
        ordered = outdoor[:1] + indoor + neutral + outdoor[1:]
    else:
        ordered = outdoor + indoor + neutral
    ordered = [item for index, item in enumerate(ordered) if item and item not in ordered[:index]] or attraction_pool
    morning = ordered[(day_index * 3) % len(ordered)]
    afternoon = ordered[(day_index * 3 + 1) % len(ordered)]
    evening = ordered[(day_index * 3 + 2) % len(ordered)]
    return morning, afternoon, evening



def _estimate_attraction_duration(name: str, category: str | None = None) -> tuple[int, str]:
    cleaned = _clean_attraction_name(name)
    category_text = (category or '').strip()
    combined = f'{cleaned} {category_text}'.strip()
    for keywords, minute_range, note in _ATTRACTION_DURATION_RULES:
        if any(keyword in combined for keyword in keywords):
            return round((minute_range[0] + minute_range[1]) / 2), note
    return 120, '适合按经典游览强度安排'



def _format_duration_minutes(minutes: int) -> str:
    if minutes >= 60:
        hours = minutes // 60
        remain = minutes % 60
        return f'{hours}小时' if remain == 0 else f'{hours}小时{remain}分钟'
    return f'{minutes}分钟'



def _parse_location_coords(value: str | None) -> tuple[float, float] | None:
    if not value or ',' not in value:
        return None
    try:
        lat_text, lng_text = value.split(',', 1)
        return float(lat_text), float(lng_text)
    except ValueError:
        return None


def _location_distance(a: str | None, b: str | None) -> float | None:
    a_coords = _parse_location_coords(a)
    b_coords = _parse_location_coords(b)
    if not a_coords or not b_coords:
        return None
    lat1, lng1 = a_coords
    lat2, lng2 = b_coords
    return ((lat1 - lat2) ** 2 + (lng1 - lng2) ** 2) ** 0.5


def _select_poi_for_day(candidates: list[dict[str, str]], anchor_name: str, day_index: int, anchor_location: str | None = None) -> dict[str, str] | None:
    if not candidates:
        return None
    anchor_tokens = [token for token in re.split(r'[·/、，,\s]+', anchor_name) if token]
    matched: list[dict[str, str]] = []
    for token in anchor_tokens:
        for candidate in candidates:
            combined = f"{candidate.get('name', '')}{candidate.get('address', '')}"
            if token and token in combined and candidate not in matched:
                matched.append(candidate)
    if matched:
        if anchor_location:
            ranked = sorted(matched, key=lambda item: _location_distance(anchor_location, item.get('location')) or 9999)
            return ranked[0]
        return matched[0]
    if anchor_location:
        ranked = sorted(candidates, key=lambda item: _location_distance(anchor_location, item.get('location')) or 9999)
        return ranked[day_index % min(len(ranked), 3)]
    return candidates[day_index % len(candidates)]



def _format_time(hour: int, minute: int = 0) -> str:
    safe_hour = max(0, min(hour, 23))
    safe_minute = max(0, min(minute, 59))
    return f'{safe_hour:02d}:{safe_minute:02d}'



def _shift_minutes(hour: int, minute: int, delta_minutes: int) -> tuple[int, int]:
    total = hour * 60 + minute + delta_minutes
    total = max(0, min(total, 23 * 60 + 59))
    return total // 60, total % 60



def _parse_duration_minutes(duration_text: str | None) -> int:
    if not duration_text:
        return 0
    hour_match = re.search(r'(\d+(?:\.\d+)?)\s*小时', duration_text)
    minute_match = re.search(r'(\d+(?:\.\d+)?)\s*分钟', duration_text)
    total = 0
    if hour_match:
        total += int(float(hour_match.group(1)) * 60)
    if minute_match:
        total += int(float(minute_match.group(1)))
    if total > 0:
        return total
    fallback = _get_route_numeric_value(duration_text)
    return int(fallback or 0)



def _estimate_drive_segments(total_minutes: int, days: int) -> list[int]:
    if days <= 1:
        return [max(total_minutes, 0)]
    total_minutes = max(total_minutes, 0)
    if total_minutes == 0:
        return [0 for _ in range(days)]
    if days == 2:
        first_day = max(min(round(total_minutes * 0.55), total_minutes), 0)
        return [first_day, max(total_minutes - first_day, 0)]
    first_day = max(min(round(total_minutes * 0.35), 360), 120)
    last_day = max(min(round(total_minutes * 0.2), 240), 90)
    if first_day + last_day >= total_minutes:
        first_day = max(round(total_minutes * 0.5), 60)
        last_day = max(total_minutes - first_day, 0)
    remaining = max(total_minutes - first_day - last_day, 0)
    middle_days = max(days - 2, 1)
    average_middle = remaining // middle_days if middle_days else remaining
    segments = [first_day]
    for index in range(middle_days):
        if index == middle_days - 1:
            used = sum(segments) + last_day
            segments.append(max(total_minutes - used, 0))
        else:
            segments.append(max(average_middle, 0))
    segments.append(last_day)
    return segments[:days]



def _build_route_day_label(destination: str, day_index: int, days: int, drive_today: int) -> str:
    if days <= 1:
        return f'{destination}当日往返'
    if day_index == 1:
        return f'{destination}出发段'
    if day_index == days:
        return f'{destination}返程准备段'
    if drive_today >= 300:
        return f'{destination}长距离中途段{day_index - 1}'
    if drive_today >= 180:
        return f'{destination}中距离中途段{day_index - 1}'
    return f'{destination}短途衔接段{day_index - 1}'



def _build_lodging_suggestion(stop_city: str, destination: str, is_last_day: bool) -> str:
    if is_last_day:
        return f'建议住在{destination}核心景区、老城区商圈或高铁站附近，兼顾游玩和返程。'
    if stop_city == '沿途中转城市':
        return '建议住在高速口附近或城市中心商圈，方便补给和第二天继续出发。'
    return f'建议住在{stop_city}高速口附近或老城区商圈，方便停车和晚餐。'



def _is_valid_attraction_name(name: str, category: str | None = None) -> bool:
    blocked = ('夜市', '商圈', '商业街', '购物中心', '广场', '本地生活', '装饰', '酒店', '海鲜酒店', '家装', '建材', '公司', '公寓', '旅舍', '客栈', '民宿', '快捷', '宾馆')
    scenic_hints = _INDOOR_HINTS + _OUTDOOR_HINTS + ('景区', '古迹', '遗址', '地标', '非遗', '博览')
    combined = f'{name} {(category or "").strip()}'.strip()
    if not name or any(token in combined for token in blocked):
        return False
    return any(token in combined for token in scenic_hints)



def _score_attraction_priority(name: str, preferences: str | None) -> int:
    score = 0
    preference_text = preferences or ''
    if '博物馆' in name or '纪念馆' in name or '美术馆' in name:
        score += 20
    if any(word in preference_text for word in ('博物馆', '展览', '艺术馆', '美术馆')) and any(token in name for token in ('博物馆', '纪念馆', '美术馆', '科技馆', '展览馆')):
        score += 60
    if any(word in preference_text for word in ('古城', '古镇', '历史', '文化', '古迹')) and any(token in name for token in ('古城', '古镇', '历史', '文化街区', '城墙', '遗址', '古迹')):
        score += 50
    if any(word in preference_text for word in ('公园', '湖', '山', '自然', '风景')) and any(token in name for token in ('公园', '湖', '山', '湿地', '步道')):
        score += 45
    if any(word in preference_text for word in ('亲子', '孩子', '小朋友')) and any(token in name for token in ('乐园', '动物园', '植物园', '海洋馆', '科技馆')):
        score += 40
    if any(token in name for token in ('地标', '塔', '寺', '街区', '非遗')):
        score += 15
    return score



def _pick_attractions(destination: str, attractions: list[str], preferences: str | None, count: int) -> list[str]:
    cleaned: list[str] = []
    for item in attractions:
        name = _clean_attraction_name(item)
        if not _is_valid_attraction_name(name):
            continue
        if name not in cleaned:
            cleaned.append(name)
    preference_text = preferences or ''
    if '博物馆' in preference_text and not any('博物馆' in item for item in cleaned):
        cleaned.insert(0, f'{destination}博物馆')
    if any(word in preference_text for word in ('古城', '古镇', '历史', '文化')) and not any(any(token in item for token in ('古城', '古镇', '历史', '文化街区', '城墙')) for item in cleaned):
        cleaned.insert(0, f'{destination}历史文化街区')
    if '公园' in preference_text and not any('公园' in item or '湖' in item or '山' in item for item in cleaned):
        cleaned.append(f'{destination}城市公园')
    fallback = [
        f'{destination}博物馆',
        f'{destination}历史文化街区',
        f'{destination}古城',
        f'{destination}城墙/古迹核心区',
        f'{destination}城市公园',
        f'{destination}地标建筑',
        f'{destination}非遗体验馆',
    ]
    for item in fallback:
        if item not in cleaned:
            cleaned.append(item)
    ranked = sorted(cleaned, key=lambda item: _score_attraction_priority(item, preferences), reverse=True)
    return ranked[:count]



def _resolve_attraction_poi(city: str, attraction_name: str) -> dict[str, str]:
    cleaned_name = _clean_attraction_name(attraction_name)
    try:
        payload = _client.place_search_by_region(cleaned_name, city, page_size=5, page_index=1)
        candidates = [item for item in _extract_poi_candidates(payload, city) if _is_valid_attraction_name(item.get('name', ''), item.get('category')) or any(token in item.get('category', '') for token in _INDOOR_HINTS + _OUTDOOR_HINTS)]
        if candidates:
            return candidates[0]
    except TencentWebServiceError:
        pass
    return {'name': cleaned_name, 'address': '', 'category': '', 'location': ''}



def _resolve_attraction_pois(city: str, attraction_names: list[str]) -> list[dict[str, str]]:
    resolved: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in attraction_names:
        poi = _resolve_attraction_poi(city, name)
        key = f"{poi.get('name', '')}|{poi.get('address', '')}"
        if key in seen:
            continue
        seen.add(key)
        resolved.append(poi)
    return resolved



def _search_foods_for_poi(city: str, poi: dict[str, str] | None, meal_keywords: list[str] | None = None) -> list[dict[str, str]]:
    if not poi:
        return []
    location = poi.get('location') or ''
    if not location:
        return _search_foods_for_location(city, None)
    collected: list[dict[str, str]] = []
    keywords = meal_keywords or _FOOD_KEYWORDS
    for keyword in keywords:
        try:
            payload = _client.place_search_nearby_sorted(keyword, location, radius=1200, page_size=5, page_index=1)
            collected.extend(_extract_poi_candidates(payload, city))
        except TencentWebServiceError:
            continue
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in collected:
        key = f"{item['name']}|{item['address']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:6]



def _search_hotels_for_poi(city: str, poi: dict[str, str] | None) -> list[dict[str, str]]:
    if not poi:
        return []
    location = poi.get('location') or ''
    if not location:
        return _search_hotels_for_city(city, None)
    collected: list[dict[str, str]] = []
    for keyword in ('酒店', '宾馆', '度假酒店', '民宿', '公寓'):
        try:
            payload = _client.place_search_nearby_sorted(keyword, location, radius=3000, page_size=8, page_index=1)
            collected.extend(_extract_poi_candidates(payload, city))
        except TencentWebServiceError:
            continue
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in collected:
        key = f"{item['name']}|{item['address']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:8]



def _build_trip_itinerary(request: TravelPlanRequest, profile: dict[str, Any], best_option: RouteOption, attractions: list[str], weather_hint: str, hotel_candidates: list[dict[str, str]] | None = None, food_candidates: list[dict[str, str]] | None = None) -> list[TripDayPlan]:
    days = int(profile['duration_days'])
    destination = request.destination
    travel_style = profile['travel_style']
    preferences = request.preferences or ''
    attraction_pool = _pick_attractions(destination, attractions, preferences, max(days * 4, 8))
    attraction_pois = _resolve_attraction_pois(destination, attraction_pool)
    itinerary: list[TripDayPlan] = []
    total_drive_minutes = _parse_duration_minutes(best_option.duration)
    drive_segments = _estimate_drive_segments(total_drive_minutes, days)
    used_attractions: set[str] = set()
    for day in range(1, days + 1):
        if '轻松' in travel_style or '老人' in preferences or '亲子' in preferences:
            pace_note = '节奏偏轻松，建议每个景点之间预留休息与机动时间。'
        else:
            pace_note = '节奏为经典游览强度，建议把核心景点放在上午与下午前段完成。'
        available_pool = [item for item in attraction_pool if item not in used_attractions]
        day_pool = available_pool[:3]
        if len(day_pool) < 3:
            fallback_pool = [item for item in attraction_pool if item not in day_pool and item in used_attractions]
            day_pool = (day_pool + fallback_pool)[:3]
        if len(day_pool) < 3:
            remainder = [item for item in attraction_pool if item not in day_pool]
            day_pool = (day_pool + remainder)[:3]
        if len(day_pool) < 3:
            day_pool = (attraction_pool + attraction_pool[:3])[:3]
        morning_spot, afternoon_spot, evening_spot = day_pool[:3]
        available_pois = [item for item in attraction_pois if item.get('name') not in used_attractions]
        base_candidates = available_pois or attraction_pois
        morning_poi = _select_poi_for_day(base_candidates, morning_spot, day - 1)
        used_names = {morning_poi.get('name')} if morning_poi and morning_poi.get('name') else set()
        afternoon_candidates = [item for item in base_candidates if item.get('name') not in used_names]
        afternoon_poi = _select_poi_for_day(afternoon_candidates or base_candidates, afternoon_spot, day, morning_poi.get('location') if morning_poi else None)
        if afternoon_poi and afternoon_poi.get('name'):
            used_names.add(afternoon_poi.get('name'))
        evening_candidates = [item for item in base_candidates if item.get('name') not in used_names]
        evening_poi = _select_poi_for_day(evening_candidates or base_candidates, evening_spot, day + 1, afternoon_poi.get('location') if afternoon_poi else (morning_poi.get('location') if morning_poi else None))
        drive_today = drive_segments[min(day - 1, len(drive_segments) - 1)] if drive_segments else 0
        morning_name = (morning_poi or {}).get('name') or morning_spot
        afternoon_name = (afternoon_poi or {}).get('name') or afternoon_spot
        evening_name = (evening_poi or {}).get('name') or evening_spot
        morning_addr = (morning_poi or {}).get('address') or ''
        afternoon_addr = (afternoon_poi or {}).get('address') or ''
        evening_addr = (evening_poi or {}).get('address') or ''
        morning_duration, morning_note = _estimate_attraction_duration(morning_name, (morning_poi or {}).get('category'))
        afternoon_duration, afternoon_note = _estimate_attraction_duration(afternoon_name, (afternoon_poi or {}).get('category'))
        evening_duration, evening_note = _estimate_attraction_duration(evening_name, (evening_poi or {}).get('category'))
        move_1 = _location_distance((morning_poi or {}).get('location'), (afternoon_poi or {}).get('location'))
        move_2 = _location_distance((afternoon_poi or {}).get('location'), (evening_poi or {}).get('location'))
        transfer_1 = 20 if move_1 is not None and move_1 < 0.03 else 40
        transfer_2 = 20 if move_2 is not None and move_2 < 0.03 else 35
        move_1_text = '两点距离较近，建议步行或短途接驳。' if transfer_1 == 20 else '两点之间建议预留 30-40 分钟交通切换。'
        move_2_text = '傍晚景点与下午景点衔接紧凑，可减少折返。' if transfer_2 == 20 else '晚间景点建议根据体力决定是否保留。'
        title = f'第{day}天：{destination}景点游览规划'

        if request.travel_mode == 'driving' and drive_today >= 180 and day < days:
            drive_start_hour, drive_start_minute = 8, 0
            drive_end_hour, drive_end_minute = _shift_minutes(drive_start_hour, drive_start_minute, drive_today)
            morning_end_hour, morning_end_minute = _shift_minutes(drive_end_hour, drive_end_minute, morning_duration)
            afternoon_start_hour, afternoon_start_minute = _shift_minutes(morning_end_hour, morning_end_minute, transfer_1 + 40)
            afternoon_end_hour, afternoon_end_minute = _shift_minutes(afternoon_start_hour, afternoon_start_minute, afternoon_duration)
            evening_start_hour, evening_start_minute = _shift_minutes(afternoon_end_hour, afternoon_end_minute, transfer_2 + 20)
            evening_end_hour, evening_end_minute = _shift_minutes(evening_start_hour, evening_start_minute, min(evening_duration, 120))
            morning = (
                f'{_format_time(drive_start_hour, drive_start_minute)}-{_format_time(morning_end_hour, morning_end_minute)} '
                f'先完成长距离抵达，预计驾驶约{max(1, round(drive_today / 60))}小时；抵达后游览 {morning_name}{f"（{morning_addr}）" if morning_addr else ""}，'
                f'建议停留 {_format_duration_minutes(morning_duration)}，{morning_note}。'
            )
            afternoon = (
                f'{_format_time(afternoon_start_hour, afternoon_start_minute)}-{_format_time(afternoon_end_hour, afternoon_end_minute)} '
                f'前往 {afternoon_name}{f"（{afternoon_addr}）" if afternoon_addr else ""}，建议停留 {_format_duration_minutes(afternoon_duration)}；'
                f'该段重点考虑与上午景点的衔接效率。{move_1_text}'
            )
            evening = (
                f'{_format_time(evening_start_hour, evening_start_minute)}-{_format_time(evening_end_hour, evening_end_minute)} '
                f'视体力补充 {evening_name}{f"（{evening_addr}）" if evening_addr else ""}，建议停留 {_format_duration_minutes(min(evening_duration, 120))}；{evening_note}。{move_2_text}'
            )
        else:
            morning_start_hour, morning_start_minute = 8, 30
            morning_end_hour, morning_end_minute = _shift_minutes(morning_start_hour, morning_start_minute, morning_duration)
            afternoon_start_hour, afternoon_start_minute = _shift_minutes(morning_end_hour, morning_end_minute, transfer_1 + 60)
            afternoon_end_hour, afternoon_end_minute = _shift_minutes(afternoon_start_hour, afternoon_start_minute, afternoon_duration)
            evening_start_hour, evening_start_minute = _shift_minutes(afternoon_end_hour, afternoon_end_minute, transfer_2 + 20)
            evening_end_hour, evening_end_minute = _shift_minutes(evening_start_hour, evening_start_minute, min(evening_duration, 120))
            morning = (
                f'{_format_time(morning_start_hour, morning_start_minute)}-{_format_time(morning_end_hour, morning_end_minute)} '
                f'上午主攻 {morning_name}{f"（{morning_addr}）" if morning_addr else ""}，建议停留 {_format_duration_minutes(morning_duration)}；'
                f'{morning_note}，如为热门博物馆/古迹类景点建议提前预约。'
            )
            afternoon = (
                f'{_format_time(afternoon_start_hour, afternoon_start_minute)}-{_format_time(afternoon_end_hour, afternoon_end_minute)} '
                f'下午转场至 {afternoon_name}{f"（{afternoon_addr}）" if afternoon_addr else ""}，建议停留 {_format_duration_minutes(afternoon_duration)}；'
                f'优先把经典看点、主展线或核心游览段放在这一时段完成。{move_1_text}'
            )
            evening = (
                f'{_format_time(evening_start_hour, evening_start_minute)}-{_format_time(evening_end_hour, evening_end_minute)} '
                f'傍晚安排 {evening_name}{f"（{evening_addr}）" if evening_addr else ""}，建议停留 {_format_duration_minutes(min(evening_duration, 120))}；'
                f'{evening_note}。{move_2_text}'
            )
        notes = [
            pace_note,
            f'天气参考：{weather_hint}',
            f'天气策略：{"优先室内景点，室外项目压缩到早晚" if any(keyword in weather_hint for keyword in ("雨", "阵雨", "雷")) else "中午避开户外暴晒，室外景点尽量安排在上午或傍晚" if any(keyword in weather_hint for keyword in ("高温", "暴晒")) else "天气相对平稳，可按常规经典顺序游览"}。',
            f'当日景点建议停留总时长约 {_format_duration_minutes(morning_duration + afternoon_duration + min(evening_duration, 120))}。',
            f'交通骨架参考：整体通行约{best_option.duration}，距离约{best_option.distance}。',
        ]
        for used_name in (morning_name, afternoon_name, evening_name):
            if used_name:
                used_attractions.add(used_name)
        itinerary.append(TripDayPlan(day=day, title=title, morning=morning, afternoon=afternoon, evening=evening, notes=notes))
    return itinerary



def _build_trip_content(
    request: TravelPlanRequest,
    profile: dict[str, Any],
    best_option: RouteOption,
    weather_hint: str,
    attractions: list[str],
    hotel_candidates: list[dict[str, str]] | None = None,
    food_candidates: list[dict[str, str]] | None = None,
) -> tuple[str, str, list[str], str, list[str], list[str], str]:
    duration_days = int(profile['duration_days'])
    budget_text = '已移除预算字段'
    destination = request.destination
    attraction_recommendations = [item for item in attractions if destination in item or any(city_hint in item for city_hint in _CITY_HINTS)]
    if not attraction_recommendations:
        attraction_recommendations = [
            f'{destination}博物馆',
            f'{destination}历史文化街区',
            f'{destination}城市公园',
        ]
    accommodation_suggestion = '住宿不作为本次行程主线，仅建议住在核心景点与交通换乘都较方便的区域。'
    transportation_suggestion = _build_transportation_suggestions(request, best_option)
    transportation_suggestion = transportation_suggestion[:3]
    travel_tips = [
        f'{duration_days}天行程按“抵达适应—经典景点深度游—返程收尾”拆分，避免每天排满。',
        '行程重点围绕经典景点的停留时长、景点间距离和天气适配来组织。',
        '热门博物馆、古迹、演出和景区门票建议提前预约；每天至少保留30-60分钟机动时间。',
        f'天气提示：{weather_hint}',
    ]
    if request.waypoints:
        travel_tips.append(f'途经点可作为去程或返程中途停留：{"、".join(w.name for w in request.waypoints)}。')
    overview = f'这是一个面向真实游玩的{destination}{duration_days}天行程规划，核心围绕经典景点的实际游览时长、景点间距离和每日天气变化来安排先后顺序；优先保证景点本身的完整体验，而不是以餐厅和住宿作为主线。'
    budget_summary = '已移除预算建议，当前重点保留景点、交通和天气策略。'
    return overview, budget_summary, transportation_suggestion, weather_hint, attraction_recommendations, travel_tips, accommodation_suggestion



def build_travel_plan(request: TravelPlanRequest) -> TravelPlanResponse:
    conversation_id = request.conversation_id or str(uuid4())
    intent = _classify_intent(f"{request.origin} {request.destination} {request.preferences or ''} {request.source_query or ''}")
    scenario = _classify_scenario(request)
    preferences = _extract_preferences(request)
    profile = _extract_trip_profile(request)
    _preference_store[conversation_id].extend(pref for pref in preferences if pref not in _preference_store[conversation_id])
    route_options, data_source, route_error, location_debug = _fetch_tencent_route_options(request, scenario)
    best_option = _choose_best_option(route_options, request)
    route_issues = _validate_route_reasonableness(best_option, request)
    destination_point = location_debug.get('destination_point')
    origin_point = location_debug.get('origin_point')
    weather_hint = _fetch_weather_hint(request.destination, destination_point)
    attraction_recommendations = _fetch_along_route_attractions(origin_point, destination_point, _infer_region_from_text(request.destination) or request.destination)
    hotel_candidates = _search_hotels_for_city(request.destination, destination_point)
    food_candidates = _search_foods_for_location(request.destination, destination_point)
    quality_note = '; '.join(route_issues) if route_issues else None
    summary = _build_summary(
        request,
        best_option,
        scenario,
        data_source,
        quality_note,
        weather_hint,
        attraction_recommendations,
        hotel_candidates,
        food_candidates,
    )
    trip_overview, budget_summary, transportation_suggestion, weather_hint, attraction_recommendations, travel_tips, accommodation_suggestion = _build_trip_content(
        request,
        profile,
        best_option,
        weather_hint,
        attraction_recommendations,
        hotel_candidates,
        food_candidates,
    )
    daily_itinerary = _build_trip_itinerary(request, profile, best_option, attraction_recommendations, weather_hint, hotel_candidates, food_candidates)
    history = _history_store[conversation_id]
    history.append(ConversationTurn(user_input=f'{request.origin} -> {request.destination}', assistant_output=summary))
    confidence = _route_quality_label(best_option.distance, best_option.duration, request) if data_source == 'tencent_maps' and not route_issues else 'low'
    if route_issues:
        route_error = '；'.join(route_issues) if route_error is None else f'{route_error}；{"；".join(route_issues)}'
    return TravelPlanResponse(
        conversation_id=conversation_id,
        intent=intent,
        scenario=scenario,
        summary=summary,
        route_title=f'{request.origin} → {request.destination} 旅游规划方案',
        trip_overview=trip_overview,
        duration_days=int(profile['duration_days']),
        budget_estimate=budget_summary,
        accommodation_suggestion=accommodation_suggestion,
        transportation_suggestion=transportation_suggestion,
        weather_hint=weather_hint,
        attraction_recommendations=attraction_recommendations,
        hotel_candidates=hotel_candidates,
        food_candidates=food_candidates,
        daily_itinerary=daily_itinerary,
        travel_tips=travel_tips,
        route_steps=best_option.steps,
        route_options=route_options,
        recommendation_reasons=best_option.reasons,
        user_preferences=_preference_store[conversation_id],
        history=list(history),
        raw_route={
            'provider': 'tencent_maps' if data_source == 'tencent_maps' else 'fallback',
            'data_source': data_source,
            'tencent_maps_key_loaded': bool(settings.tencent_maps_key),
            'best_option': best_option.model_dump(),
            'all_options': [opt.model_dump() for opt in route_options],
            'request_debug': {
                'origin': request.origin,
                'destination': request.destination,
                'travel_mode': request.travel_mode,
                'waypoints': [w.name for w in request.waypoints],
                'waypoint_order': request.waypoint_order,
                'request_source': request.request_source,
                'source_query': request.source_query,
            },
            'location_debug': location_debug,
            'trip_profile': profile,
            'weather_hint': weather_hint,
            'attractions': attraction_recommendations,
            'hotel_candidates': hotel_candidates,
            'food_candidates': food_candidates,
        },
        data_source=data_source,
        confidence=confidence,
        route_error=route_error,
    )
