from __future__ import annotations

from datetime import datetime, timezone
import inspect
from typing import Any
from uuid import uuid4

import httpx
import re

from travel_agent.core.config import get_settings
from travel_agent.core.logging import get_logger
from travel_agent.memory.redis_memory import RedisMemoryStore
from travel_agent.models.travel import (
    ConversationTurn,
    RouteOption,
    RouteStep,
    TripDayPlan,
    TravelPlanRequest,
    TravelPlanResponse,
)
from travel_agent.services.poi_candidate_service import (
    fetch_destination_poi_candidates,
    fetch_hotel_candidates,
    fetch_meal_candidates,
    fetch_route_poi_candidates,
    is_poi_in_planning_scope,
    is_valid_attraction_poi,
)
from travel_agent.services.route_stop_service import infer_route_stops
from travel_agent.services.transport_mode_service import estimate_intercity_transport_block, transport_mode_label
from travel_agent.services.trip_profile_service import build_trip_profile, decide_trip_type, score_poi
from travel_agent.services.weather_service import (
    build_daily_weather_adjustments,
    build_daily_weather_brief,
    build_weather_context,
    build_weather_plan_summary,
    build_weather_tips,
    weather_badge_for_day,
)
from travel_agent.tools.tencent_webservice_client import TencentWebServiceClient, TencentWebServiceError

settings = get_settings()
logger = get_logger(__name__)
memory_store = RedisMemoryStore()
_client = TencentWebServiceClient()
_BACKEND_STARTED_AT = datetime.now(timezone.utc).isoformat()
_WEATHER_PIPELINE_VERSION = 'daily-city-v2'


def _response_debug_metadata() -> dict[str, str]:
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'backend_started_at': _BACKEND_STARTED_AT,
        'weather_pipeline_version': _WEATHER_PIPELINE_VERSION,
    }


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
_FALLBACK_INTERCITY_ESTIMATES: dict[tuple[str, str], tuple[int, int]] = {
    ('济南', '杭州'): (857_500, 584),
    ('杭州', '济南'): (857_500, 584),
    ('济南', '徐州'): (320_000, 240),
    ('徐州', '济南'): (320_000, 240),
    ('徐州', '杭州'): (535_000, 360),
    ('杭州', '徐州'): (535_000, 360),
    ('济南', '成都'): (1_550_000, 1_080),
    ('成都', '济南'): (1_550_000, 1_080),
    ('济南', '南京'): (620_000, 420),
    ('南京', '济南'): (620_000, 420),
}

_ATTRACTION_DURATION_RULES: list[tuple[tuple[str, ...], tuple[int, int], str]] = [
    (('博物馆', '纪念馆', '美术馆', '科技馆', '展览馆', '非遗馆'), (150, 180), '适合预留完整展线参观时间'),
    (('古城', '古镇', '历史文化街区', '城墙', '遗址', '古迹'), (120, 150), '适合按主游览线分段步行游览'),
    (('公园', '湖', '湿地', '山', '步道', '滨河'), (90, 120), '适合控制为半日慢游'),
    (('寺', '塔', '教堂', '书院'), (60, 90), '适合与周边景点串联安排'),
    (('乐园', '动物园', '植物园', '海洋馆'), (180, 240), '适合预留较长体验时间'),
    (('地标', '观景台', '广场'), (45, 60), '适合作为短时打卡或傍晚收尾点'),
]


def _clean_city(value: str | None) -> str:
    return (value or '').replace('市', '').strip()


def _fallback_intercity_estimate(request: TravelPlanRequest) -> tuple[int, int] | None:
    origin = _clean_city(request.origin)
    destination = _clean_city(request.destination)
    if not origin or not destination or origin == destination:
        return None
    if (origin, destination) in _FALLBACK_INTERCITY_ESTIMATES:
        return _FALLBACK_INTERCITY_ESTIMATES[(origin, destination)]
    return 500_000, 360


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


def _extract_weather_sensitivity(request: TravelPlanRequest, profile: dict[str, Any]) -> list[str]:
    source = f"{request.preferences or ''} {request.source_query or ''} {profile.get('companions') or ''}"
    sensitivity: list[str] = []
    if any(keyword in source for keyword in ('怕热', '高温', '晒', '中暑')):
        sensitivity.append('怕热')
    if any(keyword in source for keyword in ('雨天不走户外', '下雨不户外', '雨天少户外', '怕下雨')):
        sensitivity.append('雨天不走户外')
    if any(keyword in source for keyword in ('老人', '长辈')):
        sensitivity.append('带老人')
    if any(keyword in source for keyword in ('亲子', '孩子', '小朋友')):
        sensitivity.append('亲子')
    return _dedupe_text(sensitivity)


def _memory_profile_patch(request: TravelPlanRequest, profile: dict[str, Any], preferences: list[str]) -> dict[str, Any]:
    return {
        'travel_preferences': preferences,
        'last_origin': request.origin,
        'last_destination': request.destination,
        'last_trip_type': profile.get('trip_type') or 'destination_trip',
        'preferred_pace': profile.get('pace') or 'normal',
        'interest_tags': profile.get('interest_tags', []),
        'avoid_tags': profile.get('avoid_tags', []),
        'weather_sensitivity': _extract_weather_sensitivity(request, profile),
    }


def _load_and_update_memory(active_memory_store: RedisMemoryStore, conversation_id: str, request: TravelPlanRequest, profile: dict[str, Any], preferences: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    memory_context = active_memory_store.get_context(conversation_id)
    long_term = memory_context.get('long_term', {}) if isinstance(memory_context, dict) else {}
    stored_preferences = long_term.get('travel_preferences', []) if isinstance(long_term, dict) else []
    if not isinstance(stored_preferences, list):
        stored_preferences = []
    user_preferences = list(stored_preferences)
    for pref in preferences:
        if pref not in user_preferences:
            user_preferences.append(pref)
    active_memory_store.update_profile(conversation_id, _memory_profile_patch(request, profile, user_preferences))
    short_term = memory_context.get('short_term', []) if isinstance(memory_context, dict) else []
    short_term = [item for item in short_term if isinstance(item, dict)]
    return user_preferences, short_term


def _dedupe_text(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result



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
    fallback_by_mode = {
        'driving': {
            'mode': 'DRIVING',
            'title': f'{provider_note}驾车方案',
            'distance': 12400,
            'duration': 28,
            'tags': ['RECOMMEND'],
            'reasons': ['兜底数据', '未获取真实驾车路线', '仅用于页面演示'],
        },
        'walking': {
            'mode': 'WALKING',
            'title': f'{provider_note}步行方案',
            'distance': 3200,
            'duration': 45,
            'tags': ['步行'],
            'reasons': ['兜底数据', '未获取真实步行路线', '仅用于页面演示'],
        },
        'bicycling': {
            'mode': 'BICYCLING',
            'title': f'{provider_note}骑行方案',
            'distance': 8200,
            'duration': 35,
            'tags': ['骑行'],
            'reasons': ['兜底数据', '未获取真实骑行路线', '仅用于页面演示'],
        },
        'transit': {
            'mode': 'TRANSIT',
            'title': f'{provider_note}公交方案',
            'distance': 15800,
            'duration': 34,
            'tags': ['少换乘'],
            'reasons': ['兜底数据', '未获取到真实公交路线', '仅用于页面演示'],
        },
    }
    spec = fallback_by_mode.get(request.travel_mode, fallback_by_mode['driving'])
    return [
        _build_route_option_from_route(
            {'distance': spec['distance'], 'duration': spec['duration'], 'steps': base_steps, 'mode': spec['mode'], 'tags': spec['tags'], 'toll': 0, 'traffic_light_count': 8},
            str(spec['title']),
            list(spec['reasons']),
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
    return names


def _location_quality(source: str) -> str:
    if source == 'region_center':
        return 'low'
    if source in {'coordinate', 'geocoder', 'place_search', 'suggestion', 'place_search_fallback', 'suggestion_fallback'}:
        return 'high'
    return 'unknown'


def _extract_reverse_adcode(payload: dict[str, Any]) -> str | None:
    result = payload.get('result') if isinstance(payload, dict) else {}
    ad_info = result.get('ad_info') if isinstance(result, dict) else {}
    adcode = ad_info.get('adcode') if isinstance(ad_info, dict) else None
    return str(adcode) if adcode else None



def _fetch_tencent_route_options(request: TravelPlanRequest, scenario: str) -> tuple[list[RouteOption], str, str | None, dict[str, str]]:
    if not settings.tencent_maps_key:
        return _fallback_routes(request, scenario, 'missing_key'), 'fallback', 'Tencent Maps key is not configured', {'reason': 'missing_key'}

    endpoint = TENCENT_ROUTE_ENDPOINTS.get(request.travel_mode)
    if not endpoint:
        return _fallback_routes(request, scenario, 'unsupported_mode'), 'fallback', f'Unsupported travel mode: {request.travel_mode}', {'reason': 'unsupported_mode'}

    waypoint_names = _sort_waypoints(request)
    waypoint_coords: list[str] = []
    location_debug: dict[str, Any] = {}
    try:
        origin_region = _infer_region_from_text(request.origin)
        destination_region = _infer_region_from_text(request.destination) or origin_region
        origin_point, origin_source = _resolve_location_point(request.origin, region=origin_region)
        destination_point, destination_source = _resolve_location_point(request.destination, region=destination_region)
        location_debug['origin_source'] = origin_source
        location_debug['destination_source'] = destination_source
        location_debug['origin_quality'] = _location_quality(origin_source)
        location_debug['destination_quality'] = _location_quality(destination_source)
        if not origin_point:
            raise TencentMapsError(f'Unable to resolve origin: {request.origin} via {origin_source}')
        if not destination_point:
            raise TencentMapsError(f'Unable to resolve destination: {request.destination} via {destination_source}')
        location_debug['origin_point'] = origin_point
        location_debug['destination_point'] = destination_point
        if location_debug['origin_quality'] == 'low' or location_debug['destination_quality'] == 'low':
            location_debug['reason'] = 'low_geocode_quality'
            return _fallback_routes(request, scenario, 'low_geocode_quality'), 'fallback', '关键地点只解析到城市中心，已返回兜底路线。', location_debug
        if settings.tencent_maps_key:
            try:
                adcode = _extract_reverse_adcode(_client.reverse_geocoder(destination_point))
                if adcode:
                    location_debug['destination_adcode'] = adcode
            except Exception:
                logger.debug('Destination reverse geocoder failed while preparing route debug', exc_info=True)
                location_debug['destination_adcode_error'] = 'reverse_geocoder_failed'
        for waypoint in waypoint_names:
            waypoint_point, waypoint_source = _resolve_location_point(waypoint, region=_infer_region_from_text(waypoint) or origin_region)
            if not waypoint_point:
                raise TencentMapsError(f'Unable to resolve waypoint: {waypoint} via {waypoint_source}')
            waypoint_coords.append(waypoint_point)
            location_debug[f'waypoint:{waypoint}'] = waypoint_source
            try:
                waypoint_adcode = _extract_reverse_adcode(_client.reverse_geocoder(waypoint_point))
                if waypoint_adcode:
                    location_debug[f'waypoint_adcode:{waypoint}'] = waypoint_adcode
            except Exception:
                location_debug[f'waypoint_adcode_error:{waypoint}'] = 'reverse_geocoder_failed'
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
    if request.waypoint_order and waypoint_coords and request.travel_mode != 'driving':
        location_debug.setdefault('warnings', []).append('当前交通方式不支持途经点自动排序，已保留用户输入顺序。')
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


def fetch_route_options(request: TravelPlanRequest, profile: dict[str, Any] | None = None) -> tuple[list[RouteOption], str, str | None, dict[str, str]]:
    return _fetch_tencent_route_options(request, _classify_scenario(request))


def build_route_context(request: TravelPlanRequest, profile: dict[str, Any], route_options: list[RouteOption], data_source: str, location_debug: dict[str, Any]) -> dict[str, Any]:
    best_option = _choose_best_option(route_options, request)
    return _build_route_context(request, best_option, profile, location_debug, data_source)


def fetch_poi_candidates(request: TravelPlanRequest, profile: dict[str, Any], route_context: dict[str, Any], location_debug: dict[str, Any] | None = None) -> dict[str, Any]:
    stage_counts = route_context.get('stage_counts') if isinstance(route_context.get('stage_counts'), dict) else {}
    route_days = int(stage_counts.get('route_days') or profile.get('route_days') or 0)
    waypoint_details = [dict(item) for item in profile.get('waypoint_details') or [] if isinstance(item, dict)]
    profile_route_stops = [dict(item) for item in profile.get('route_stops') or [] if isinstance(item, dict)]
    request_waypoints = [item.model_dump() for item in request.waypoints]
    merged_waypoints: list[dict[str, Any]] = []
    for item in [*profile_route_stops, *request_waypoints, *waypoint_details]:
        name = str(item.get('name') or '').strip()
        if name and not any(existing.get('name') == name for existing in merged_waypoints):
            merged_waypoints.append(item)
    enriched_profile = {**profile, 'destination': request.destination}
    context_route_stops = route_context.get('route_stops') if isinstance(route_context.get('route_stops'), list) else None
    route_stops = [dict(item) for item in context_route_stops if isinstance(item, dict) and item.get('name')] if context_route_stops else infer_route_stops(
        request.origin,
        request.destination,
        route_days,
        waypoints=merged_waypoints,
        route_context=route_context,
    )
    enriched_profile['route_stops'] = route_stops
    route_candidates = fetch_route_poi_candidates(route_stops, enriched_profile, route_context)
    destination_candidates = fetch_destination_poi_candidates(request.destination, enriched_profile, route_context)
    anchor_points = route_stops + [{'name': request.destination, 'type': 'destination'}]
    return {
        'route_stops': route_stops,
        'route_candidates': route_candidates,
        'destination_candidates': destination_candidates,
        'hotel_candidates': fetch_hotel_candidates(anchor_points, profile),
        'food_candidates': fetch_meal_candidates(anchor_points, profile),
        'candidate_debug': {
            'route_days': route_days,
            'destination': request.destination,
            'data_source': route_context.get('data_source') or 'fallback',
        },
    }


def rank_poi_candidates(poi_candidates: dict[str, Any], profile: dict[str, Any], route_context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    ranked: dict[str, list[dict[str, Any]]] = {}
    weather_context = route_context.get('weather_context') if isinstance(route_context.get('weather_context'), dict) else {}
    daily_weather = weather_context.get('daily_weather') if isinstance(weather_context, dict) else []
    first_weather = daily_weather[0] if weather_context.get('data_source') == 'tencent_maps' and isinstance(daily_weather, list) and daily_weather else None
    for key, stage in (('route_candidates', 'route'), ('destination_candidates', 'destination')):
        scored: list[dict[str, Any]] = []
        for item in poi_candidates.get(key, []) or []:
            enriched = dict(item)
            score = score_poi(enriched, profile, {**route_context, 'stage': stage, 'weather_day': first_weather, 'daily_available_visit_minutes': enriched.get('estimated_minutes') or 240})
            enriched['score'] = score['final_score']
            enriched['reason'] = score['reason']
            enriched['tags'] = '、'.join(str(tag) for tag in score.get('tags', [])) if isinstance(score.get('tags'), list) else ''
            scored.append(enriched)
        ranked[key] = sorted(scored, key=lambda item: float(item.get('score') or 0), reverse=True)
    return ranked


def build_daily_itinerary(
    request: TravelPlanRequest,
    profile: dict[str, Any],
    route_context: dict[str, Any],
    ranked_pois: dict[str, list[dict[str, Any]]],
    route_options: list[RouteOption],
    weather_hint: str | None = None,
    hotel_candidates: list[dict[str, str]] | None = None,
    food_candidates: list[dict[str, str]] | None = None,
) -> list[TripDayPlan]:
    best_option = _choose_best_option(route_options, request)
    attraction_names = _dedupe_text(
        [
            *[str(item.get('name')) for item in ranked_pois.get('route_candidates', []) if item.get('name')],
            *[str(item.get('name')) for item in ranked_pois.get('destination_candidates', []) if item.get('name')],
        ]
    )
    return _build_trip_itinerary(
        request,
        profile,
        best_option,
        attraction_names,
        weather_hint or f'建议出行前查看{request.destination}未来 7 天天气。',
        route_context,
        hotel_candidates,
        food_candidates,
        ranked_pois,
    )



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


def _distance_text_to_meters(text: str | None) -> int:
    if not text:
        return 0
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if not match:
        return 0
    value = float(match.group(1))
    if 'km' in text or '公里' in text:
        return int(value * 1000)
    return int(value)


def _duration_text_to_minutes(text: str | None) -> int:
    return _parse_duration_minutes(text)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == '':
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_stage_counts(profile: dict[str, Any]) -> dict[str, Any]:
    total_days = max(1, int(profile.get('duration_days') or 1))
    route_days = _int_or_none(profile.get('route_days'))
    destination_days = _int_or_none(profile.get('destination_days'))
    explicit_total = _int_or_none(profile.get('explicit_total_days'))
    stage_mode = str(profile.get('stage_plan_mode') or 'mixed_unspecified')
    notes: list[str] = []

    if route_days is None and destination_days is None:
        if profile.get('trip_type') == 'along_route_trip':
            route_days = total_days
            destination_days = 0
            stage_mode = 'route_only'
        else:
            route_days = 0
            destination_days = total_days
            stage_mode = 'destination_only'
    elif route_days is None:
        route_days = max(0, total_days - max(0, destination_days or 0))
    elif destination_days is None:
        destination_days = max(0, total_days - max(0, route_days))

    route_days = max(0, route_days or 0)
    destination_days = max(0, destination_days or 0)
    stage_sum = route_days + destination_days
    if explicit_total is not None and explicit_total > stage_sum:
        total_days = explicit_total
        notes.append(f'用户明确总共{explicit_total}天，阶段合计{stage_sum}天，已保留{explicit_total - stage_sum}天作为机动/返程缓冲。')
    elif explicit_total is not None and explicit_total < stage_sum:
        original_route_days = route_days
        original_destination_days = destination_days
        total_days = explicit_total
        route_days = min(route_days, total_days)
        destination_days = min(destination_days, max(0, total_days - route_days))
        notes.append(
            f'明确总时长{explicit_total}天与阶段拆分{original_route_days}+{original_destination_days}天冲突，'
            f'已保留明确总时长并压缩为途中{route_days}天、目的地{destination_days}天。'
        )
    elif stage_sum > total_days:
        notes.append(f'阶段拆分合计{stage_sum}天超过原始总天数{total_days}天，已按阶段天数重新计算。')
        total_days = stage_sum
    elif stage_sum and stage_sum < total_days:
        notes.append(f'阶段拆分合计{stage_sum}天，剩余{total_days - stage_sum}天作为机动/返程缓冲。')

    stage_sum = route_days + destination_days
    buffer_days = max(0, total_days - stage_sum)
    if route_days > 0 and destination_days > 0:
        stage_mode = 'route_then_destination'
    elif route_days > 0:
        stage_mode = 'route_only'
    elif destination_days > 0:
        stage_mode = 'destination_only'
    return {
        'total_days': total_days,
        'route_days': route_days,
        'destination_days': destination_days,
        'buffer_days': buffer_days,
        'stage_plan_mode': stage_mode,
        'stage_notes': notes,
    }


def _activity_minutes_for_profile(profile: dict[str, Any]) -> int:
    return 600 if profile.get('pace') == 'intensive' else 540 if profile.get('pace') == 'normal' else 480


def _segment_visit_minutes(profile: dict[str, Any], drive_minutes: int) -> int:
    return max(90, _activity_minutes_for_profile(profile) - max(0, drive_minutes))


def _estimate_segment_distances(total_meters: int, count: int) -> list[int]:
    if count <= 0:
        return []
    if total_meters <= 0:
        return [0 for _ in range(count)]
    base = max(0, total_meters // count)
    distances = [base for _ in range(count)]
    distances[-1] += max(0, total_meters - base * count)
    return distances


def _intercity_mode_for_profile(profile: dict[str, Any], request: TravelPlanRequest) -> str:
    mode = str(profile.get('intercity_mode') or '').strip()
    if mode:
        return mode
    if request.travel_mode in {'driving', 'transit'}:
        return request.travel_mode
    return 'driving'


def _transport_block_for_segment(
    *,
    request: TravelPlanRequest,
    profile: dict[str, Any],
    origin: str,
    destination: str,
    distance_meters: int,
    drive_minutes: int,
) -> dict[str, Any]:
    intercity_mode = _intercity_mode_for_profile(profile, request)
    return estimate_intercity_transport_block(
        origin=origin,
        destination=destination,
        mode=intercity_mode,
        distance_meters=distance_meters,
        fallback_minutes=drive_minutes,
    )


def _supports_keyword(func: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    if keyword in signature.parameters:
        return True
    return any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())


def _build_weather_context_for_plan(
    *,
    destination: str,
    route_stops: list[dict[str, Any]],
    days: int,
    location_debug: dict[str, Any],
    daily_plan_context: list[dict[str, Any]],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        'route_stops': route_stops,
        'days': days,
        'location_debug': location_debug,
    }
    if _supports_keyword(build_weather_context, 'daily_plan_context'):
        kwargs['daily_plan_context'] = daily_plan_context
    return build_weather_context(destination, **kwargs)


def _route_stops_for_segments(request: TravelPlanRequest, profile: dict[str, Any], route_context: dict[str, Any], route_days: int, destination_days: int) -> list[dict[str, Any]]:
    existing = route_context.get('route_stops') if isinstance(route_context.get('route_stops'), list) else None
    if existing:
        return [dict(item) for item in existing if isinstance(item, dict) and item.get('name')]
    profile_stops = [dict(item) for item in profile.get('route_stops') or [] if isinstance(item, dict) and item.get('name')]
    if profile_stops:
        return infer_route_stops(request.origin, request.destination, max(route_days, len(profile_stops)), waypoints=profile_stops, route_context=route_context)
    intermediate_days = max(0, route_days - 1) if destination_days > 0 else route_days
    return infer_route_stops(request.origin, request.destination, intermediate_days, waypoints=[], route_context=route_context)


def build_stage_segments(request: TravelPlanRequest, profile: dict[str, Any], route_context: dict[str, Any]) -> list[dict[str, Any]]:
    stage_counts = route_context.get('stage_counts') if isinstance(route_context.get('stage_counts'), dict) else _resolve_stage_counts(profile)
    total_days = int(stage_counts.get('total_days') or profile.get('duration_days') or 1)
    route_days = int(stage_counts.get('route_days') or profile.get('route_days') or 0)
    destination_days = int(stage_counts.get('destination_days') or profile.get('destination_days') or 0)
    route_stops = _route_stops_for_segments(request, profile, route_context, route_days, destination_days)
    route_stops = sorted(route_stops, key=lambda item: int(item.get('stage_day') or item.get('preferred_day') or 999))
    route_targets: list[dict[str, Any]] = []
    for stop in route_stops:
        try:
            stay_amount = float(stop.get('stay_days') or stop.get('stay_nights') or 0)
        except (TypeError, ValueError):
            stay_amount = 0
        repeat_count = max(1, int(stay_amount) if stay_amount.is_integer() else int(stay_amount) + 1)
        for repeat_index in range(repeat_count):
            route_targets.append({**stop, 'stage_day': len(route_targets) + 1, 'local_stay_day': repeat_index > 0})
            if len(route_targets) >= route_days:
                break
        if len(route_targets) >= route_days:
            break
    while len(route_targets) < route_days:
        if route_targets:
            route_targets.append({**route_targets[-1], 'stage_day': len(route_targets) + 1, 'local_stay_day': True})
        else:
            route_targets.append({'name': request.destination, 'type': 'destination_fallback', 'stage_day': len(route_targets) + 1, 'stay_days': 1, 'stay_nights': 0, 'data_source': 'destination_fallback'})
    total_minutes = int(route_context.get('route_total_duration_minutes') or 0)
    total_meters = int(route_context.get('route_total_distance_meters') or 0)
    drive_segments = _estimate_drive_segments(total_minutes, max(1, len(route_targets))) if route_targets else []
    distance_segments = _estimate_segment_distances(total_meters, max(1, len(route_targets))) if route_targets else []
    segment_source = 'tencent_maps' if route_context.get('data_source') == 'tencent_maps' and len(route_targets) <= 1 else 'fallback_estimated'
    segments: list[dict[str, Any]] = []
    current_origin = request.origin
    for index, target in enumerate(route_targets, start=1):
        target_name = str(target.get('name') or request.destination)
        drive_minutes = drive_segments[index - 1] if index - 1 < len(drive_segments) else 0
        segment_distance = distance_segments[index - 1] if index - 1 < len(distance_segments) else 0
        is_local_day = _clean_city(current_origin) == _clean_city(target_name)
        if is_local_day:
            drive_minutes = 35
            segment_distance = 0
            local_mode = str(profile.get('local_mode') or request.travel_mode)
            transport_block = {
                'mode': local_mode,
                'label': transport_mode_label(local_mode, local=True),
                'origin': target_name,
                'destination': target_name,
                'total_minutes': drive_minutes,
                'summary': f'市内转场约{_format_duration_minutes(drive_minutes)}',
            }
            route_segment = f'{target_name}市内/周边'
        else:
            pair_estimate = _FALLBACK_INTERCITY_ESTIMATES.get((_clean_city(current_origin), _clean_city(target_name)))
            if segment_source == 'fallback_estimated' and pair_estimate:
                segment_distance = pair_estimate[0]
                drive_minutes = pair_estimate[1]
            transport_block = _transport_block_for_segment(
                request=request,
                profile=profile,
                origin=current_origin,
                destination=target_name,
                distance_meters=segment_distance,
                drive_minutes=drive_minutes,
            )
            route_segment = f'{current_origin} → {target_name}'
        transfer_minutes = int(transport_block.get('total_minutes') or drive_minutes)
        segments.append(
            {
                'day': index,
                'stage': 'route',
                'stage_label': 'route',
                'origin': current_origin,
                'destination': target_name,
                'anchor_city': target_name,
                'route_segment': route_segment,
                'planned_stay_days': 1,
                'planned_stay_nights': target.get('stay_nights', 0),
                'drive_minutes': transfer_minutes,
                'transport_minutes': transfer_minutes,
                'visit_minutes': _segment_visit_minutes(profile, transfer_minutes),
                'transport_block': transport_block,
                'data_source': segment_source,
            }
        )
        current_origin = target_name
    for day in range(route_days + 1, route_days + destination_days + 1):
        is_destination_transition = _clean_city(current_origin) != _clean_city(request.destination)
        if is_destination_transition:
            pair_estimate = _FALLBACK_INTERCITY_ESTIMATES.get((_clean_city(current_origin), _clean_city(request.destination)))
            segment_distance, drive_minutes = pair_estimate or (max(0, total_meters), max(120, total_minutes))
            transport_block = _transport_block_for_segment(
                request=request,
                profile=profile,
                origin=current_origin,
                destination=request.destination,
                distance_meters=segment_distance,
                drive_minutes=drive_minutes,
            )
            drive_minutes = int(transport_block.get('total_minutes') or drive_minutes)
            route_segment = f'{current_origin} → {request.destination}'
        else:
            drive_minutes = 45 if day == route_days + 1 else 30
            local_mode = str(profile.get('local_mode') or request.travel_mode)
            transport_block = {
                'mode': local_mode,
                'label': transport_mode_label(local_mode, local=True),
                'origin': request.destination,
                'destination': request.destination,
                'total_minutes': drive_minutes,
                'summary': f'市内转场约{_format_duration_minutes(drive_minutes)}',
            }
            route_segment = f'{request.destination}市内/周边'
        segments.append(
            {
                'day': day,
                'stage': 'destination',
                'stage_label': 'destination',
                'origin': current_origin,
                'destination': request.destination,
                'anchor_city': request.destination,
                'route_segment': route_segment,
                'planned_stay_days': 1,
                'planned_stay_nights': 0,
                'drive_minutes': drive_minutes,
                'transport_minutes': drive_minutes,
                'visit_minutes': _segment_visit_minutes(profile, drive_minutes),
                'transport_block': transport_block,
                'data_source': 'fallback_estimated',
            }
        )
        current_origin = request.destination
    for day in range(route_days + destination_days + 1, total_days + 1):
        segments.append(
            {
                'day': day,
                'stage': 'buffer',
                'stage_label': 'buffer',
                'origin': request.destination,
                'destination': request.destination,
                'anchor_city': request.destination,
                'route_segment': f'{request.destination}机动/返程缓冲',
                'planned_stay_days': 0,
                'planned_stay_nights': 0,
                'drive_minutes': 60,
                'transport_minutes': 60,
                'visit_minutes': _segment_visit_minutes(profile, 60),
                'transport_block': {
                    'mode': str(profile.get('local_mode') or request.travel_mode),
                    'label': transport_mode_label(str(profile.get('local_mode') or request.travel_mode), local=True),
                    'origin': request.destination,
                    'destination': request.destination,
                    'total_minutes': 60,
                    'summary': '机动/返程缓冲约1小时',
                },
                'data_source': 'fallback_estimated',
            }
        )
    return segments[:total_days]


def _build_route_context(request: TravelPlanRequest, best_option: RouteOption, profile: dict[str, Any], location_debug: dict[str, Any], data_source: str) -> dict[str, Any]:
    total_minutes = _duration_text_to_minutes(best_option.duration)
    total_meters = _distance_text_to_meters(best_option.distance)
    fallback_estimate = _fallback_intercity_estimate(request) if data_source != 'tencent_maps' and (total_minutes < 120 or total_meters < 80_000) else None
    if fallback_estimate:
        total_meters, total_minutes = fallback_estimate
        location_debug = {**location_debug, 'fallback_segment_estimate': 'intercity_city_pair'}
    stage_counts = _resolve_stage_counts(profile)
    days = int(stage_counts['total_days'])
    route_days = int(stage_counts['route_days'])
    destination_days = int(stage_counts['destination_days'])
    daily_drive_minutes = _estimate_drive_segments(total_minutes, max(1, route_days)) if route_days else []
    daily_context: list[dict[str, Any]] = []
    for index in range(1, days + 1):
        if index <= route_days:
            stage = 'route'
            stage_day = index
            drive_minutes = daily_drive_minutes[index - 1] if index - 1 < len(daily_drive_minutes) else 0
        elif index <= route_days + destination_days:
            stage = 'destination'
            stage_day = index - route_days
            drive_minutes = 20 if index == route_days + 1 and route_days > 0 else 0
        else:
            stage = 'buffer'
            stage_day = index - route_days - destination_days
            drive_minutes = min(90, max(0, total_minutes // max(1, days))) if index == days else 0
        activity_minutes = 600 if profile.get('pace') == 'intensive' else 540 if profile.get('pace') == 'normal' else 480
        available = max(90, activity_minutes - drive_minutes)
        if stage == 'buffer':
            recommended_spots = 1
        elif stage == 'destination' and profile.get('pace') == 'relaxed':
            recommended_spots = 2
        elif stage == 'destination':
            recommended_spots = 3 if available >= 300 else 2
        elif request.travel_mode == 'driving' and drive_minutes > 300:
            recommended_spots = 1
        elif request.travel_mode == 'driving' and drive_minutes >= 120:
            recommended_spots = 2
        elif request.travel_mode in {'walking', 'bicycling'} and total_meters > 80_000:
            recommended_spots = 1
        else:
            recommended_spots = 3 if available >= 300 else 2
        daily_context.append(
            {
                'day': index,
                'stage': stage,
                'stage_day': stage_day,
                'daily_drive_minutes': drive_minutes,
                'daily_available_visit_minutes': available,
                'recommended_spots': recommended_spots,
            }
        )
    warnings: list[str] = []
    if request.travel_mode in {'walking', 'bicycling'} and total_meters > 80_000:
        warnings.append('当前起终点距离较长，不适合全程步行/骑行，建议改为城市内分段体验或更换交通方式。')
    if request.travel_mode == 'transit' and data_source != 'tencent_maps':
        warnings.append('公共交通跨城车次需以实际购票平台为准，当前仅提供行程结构建议。')
    context = {
        'route_total_duration_minutes': total_minutes,
        'route_total_distance_meters': total_meters,
        'route_total_duration': best_option.duration,
        'route_total_distance': best_option.distance,
        'stage_counts': stage_counts,
        'daily_plan_context': daily_context,
        'origin_point': location_debug.get('origin_point'),
        'destination_point': location_debug.get('destination_point'),
        'data_source': data_source,
        'warnings': warnings,
    }
    stage_segments = build_stage_segments(request, profile, context)
    segment_by_day = {int(item.get('day') or 0): item for item in stage_segments}
    for item in daily_context:
        segment = segment_by_day.get(int(item.get('day') or 0))
        if not segment:
            continue
        item['stage'] = segment.get('stage') or item.get('stage')
        item['anchor_city'] = segment.get('anchor_city')
        item['route_segment'] = segment.get('route_segment')
        item['segment_data_source'] = segment.get('data_source')
        item['daily_drive_minutes'] = int(segment.get('drive_minutes') or item.get('daily_drive_minutes') or 0)
        item['transport_minutes'] = int(segment.get('transport_minutes') or item.get('daily_drive_minutes') or 0)
        item['transport_block'] = segment.get('transport_block')
        item['daily_available_visit_minutes'] = int(segment.get('visit_minutes') or item.get('daily_available_visit_minutes') or 0)
        if item['stage'] == 'destination':
            item['recommended_spots'] = 3 if item['daily_available_visit_minutes'] >= 300 else 2
        elif isinstance(item.get('transport_block'), dict) and item['transport_block'].get('mode') not in {'driving', None} and item['daily_drive_minutes'] >= 240:
            item['recommended_spots'] = 1 if item['daily_drive_minutes'] > 300 else 2
        elif request.travel_mode == 'driving' and item['daily_drive_minutes'] > 300:
            item['recommended_spots'] = 1
        elif request.travel_mode == 'driving' and item['daily_drive_minutes'] >= 120:
            item['recommended_spots'] = 2
    context['stage_segments'] = stage_segments
    context['route_stops'] = [dict(item) for item in _route_stops_for_segments(request, profile, context, route_days, destination_days)]
    return context



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
    base_profile = build_trip_profile(request)
    travel_style = str(base_profile.get('travel_style') or ('轻松慢游' if any(word in text for word in ('轻松', '慢游', '休闲', '不赶')) else '常规游玩'))
    companions = str(base_profile.get('companions') or ('家庭/朋友' if any(word in text for word in ('家人', '家庭', '朋友', '亲子')) else '默认'))
    return {
        'duration_days': int(base_profile.get('duration_days') or days),
        'nights': base_profile.get('nights') or nights,
        'budget': base_profile.get('budget') or budget,
        'travel_style': travel_style,
        'companions': companions,
        'interest_tags': base_profile.get('interest_tags', []),
        'avoid_tags': base_profile.get('avoid_tags', []),
        'pace': base_profile.get('pace', 'normal'),
        'trip_type': base_profile.get('trip_type', 'destination_trip'),
        'route_days': base_profile.get('route_days'),
        'destination_days': base_profile.get('destination_days'),
        'buffer_days': base_profile.get('buffer_days'),
        'route_nights': base_profile.get('route_nights'),
        'destination_nights': base_profile.get('destination_nights'),
        'route_stops': base_profile.get('route_stops', []),
        'destination_stay_days': base_profile.get('destination_stay_days'),
        'total_days_source': base_profile.get('total_days_source'),
        'duration_source': base_profile.get('duration_source'),
        'stage_plan_mode': base_profile.get('stage_plan_mode'),
        'explicit_total_days': base_profile.get('explicit_total_days'),
        'waypoint_details': base_profile.get('waypoint_details', []),
        'must_visit_attractions': base_profile.get('must_visit_attractions', []),
        'waypoint_order_mode': base_profile.get('waypoint_order_mode', 'unspecified'),
        'intercity_mode': base_profile.get('intercity_mode') or request.travel_mode,
        'intercity_label': base_profile.get('intercity_label') or transport_mode_label(base_profile.get('intercity_mode') or request.travel_mode),
        'local_mode': base_profile.get('local_mode') or request.travel_mode,
        'local_label': base_profile.get('local_label') or transport_mode_label(base_profile.get('local_mode') or request.travel_mode, local=True),
        'transport_preference_source': base_profile.get('transport_preference_source') or 'default',
        'source_text': source_text,
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



def _weather_hint_from_context(destination: str, weather_context: dict[str, Any], fallback_hint: str | None = None) -> str:
    if weather_context.get('data_source') == 'fallback':
        return f'{_clean_city(destination)}天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。'
    return str(weather_context.get('summary') or fallback_hint or f'建议出行前查看{destination}未来 7 天天气。')


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
    for keyword in _ATTRACTION_KEYWORDS[:4]:
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
    for keyword in _HOTEL_KEYWORDS[:2]:
        try:
            payload = _client.place_search_by_region(keyword, city, page_size=5, page_index=1)
            collected.extend(_extract_poi_candidates(payload, city))
        except TencentWebServiceError:
            continue
    if center_point:
        for keyword in ('酒店',):
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
        for keyword in _FOOD_KEYWORDS[:3]:
            try:
                payload = _client.place_search_nearby_sorted(keyword, center_point, radius=1800, page_size=6, page_index=1)
                collected.extend(_extract_poi_candidates(payload, city))
            except TencentWebServiceError:
                continue
    else:
        for keyword in _FOOD_KEYWORDS[:3]:
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
    profile = request.trip_profile if isinstance(request.trip_profile, dict) else {}
    intercity_mode = str(profile.get('intercity_mode') or request.travel_mode)
    local_mode = str(profile.get('local_mode') or request.travel_mode)
    intercity_label = transport_mode_label(intercity_mode)
    local_label = transport_mode_label(local_mode, local=True)
    mode_labels = {
        'driving': '驾车',
        'walking': '步行',
        'transit': '公共交通',
        'bicycling': '骑行',
    }
    if intercity_mode in {'high_speed_rail', 'train', 'flight', 'coach'}:
        suggestions.append(f'跨城段建议以{intercity_label}为主，市内采用{local_label}接驳；跨城时间需额外预留进站候车、出站接驳和行李整理。')
        suggestions.append('高铁/火车/航班班次以购票平台为准，建议把固定票务时间作为当天上午或下午的硬约束。')
    else:
        suggestions.append(f'当前推荐以{mode_labels.get(request.travel_mode, request.travel_mode)}为主，预计 {best_option.duration} / {best_option.distance}。')
    if intercity_mode == 'driving' or (request.travel_mode == 'driving' and intercity_mode not in {'high_speed_rail', 'train', 'flight', 'coach'}):
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
    interest_tags = request.trip_profile.get('interest_tags', []) if isinstance(request.trip_profile, dict) else []
    avoid_tags = request.trip_profile.get('avoid_tags', []) if isinstance(request.trip_profile, dict) else []
    summary_lines = [
        f'{request.origin}到{request.destination}{profile["duration_days"]}天旅游规划',
        f'建议以{mode_labels.get(request.travel_mode, request.travel_mode)}为主，整体通行时间约{option.duration}，适合作为这次行程的交通骨架。',
        f'旅行风格为{profile["travel_style"]}，重点关注景点串联与路程衔接。',
        f'途经安排：{waypoint_text}。',
        f'规划侧重点：{preference_text}',
    ]
    if interest_tags:
        summary_lines.append(f'偏好命中：{"、".join(str(tag) for tag in interest_tags)}。')
    if avoid_tags:
        summary_lines.append(f'规避要求：{"、".join(str(tag) for tag in avoid_tags)}。')
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
    return 120, '适合按常规游览节奏安排'



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


def _format_candidate_label(item: dict[str, str] | None) -> str:
    if not item:
        return ''
    name = item.get('name', '').strip()
    address = item.get('address', '').strip()
    if not name:
        return ''
    return f'{name}（{address}）' if address else name


def _pick_nearby_candidate(candidates: list[dict[str, str]], anchor_location: str | None, day_index: int) -> dict[str, str] | None:
    if not candidates:
        return None
    if anchor_location:
        ranked = sorted(candidates, key=lambda item: _location_distance(anchor_location, item.get('location')) or 9999)
        return ranked[day_index % min(len(ranked), 3)]
    return candidates[day_index % len(candidates)]


def _build_meal_and_hotel_notes(
    city: str,
    morning_poi: dict[str, str] | None,
    afternoon_poi: dict[str, str] | None,
    evening_poi: dict[str, str] | None,
    hotel_candidates: list[dict[str, str]] | None,
    food_candidates: list[dict[str, str]] | None,
    day_index: int,
) -> list[str]:
    lunch_anchor = afternoon_poi or morning_poi
    dinner_anchor = evening_poi or afternoon_poi or morning_poi
    hotel_anchor = evening_poi or afternoon_poi or morning_poi
    lunch_options = food_candidates or []
    dinner_options = food_candidates or []
    hotel_options = hotel_candidates or []
    lunch = _pick_nearby_candidate(lunch_options, (lunch_anchor or {}).get('location'), day_index)
    dinner = _pick_nearby_candidate(dinner_options, (dinner_anchor or {}).get('location'), day_index + 1)
    hotel = _pick_nearby_candidate(hotel_options, (hotel_anchor or {}).get('location'), day_index)
    notes: list[str] = []
    lunch_label = _format_candidate_label(lunch)
    dinner_label = _format_candidate_label(dinner)
    hotel_label = _format_candidate_label(hotel)
    if lunch_label:
        notes.append(f'午餐建议靠近{(lunch_anchor or {}).get("name") or "上午/下午景点"}：{lunch_label}。')
    else:
        notes.append('午餐建议选择上午景点与下午景点之间 1-2 公里范围内的本地餐厅，减少折返。')
    if dinner_label:
        notes.append(f'晚餐建议靠近{(dinner_anchor or {}).get("name") or "傍晚景点"}：{dinner_label}。')
    else:
        notes.append('晚餐建议放在傍晚景点或住宿点附近，方便结束后休息。')
    if hotel_label:
        notes.append(f'住宿建议靠近当天收尾景点：{hotel_label}。')
    else:
        notes.append('住宿建议选择当天收尾景点附近或公共交通换乘方便的商圈。')
    return notes



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


def _effective_weather_day(weather_context: dict[str, Any], weather_day: dict[str, Any] | None) -> dict[str, Any] | None:
    if not weather_day:
        return None
    day_source = str(weather_day.get('data_source') or weather_context.get('data_source') or '')
    if day_source != 'tencent_maps':
        return None
    return weather_day


def _fallback_attraction_names_for_city(city: str) -> list[str]:
    clean = _clean_city(city) or city
    return [f'{clean}博物馆', f'{clean}风景名胜区', f'{clean}历史文化街区', f'{clean}公园', f'{clean}古城']


def normalize_poi_identity(poi: dict[str, Any]) -> str:
    name = _clean_attraction_name(str(poi.get('name') or poi.get('title') or ''))
    address = str(poi.get('address') or '').strip()
    source = name or address
    normalized = re.sub(r'[\s·,，。:：;；()（）/|｜\-]+', '', source)
    return normalized.replace('市', '')


def classify_poi_bucket(poi: dict[str, Any]) -> str:
    combined = ' '.join(str(poi.get(key) or '') for key in ('name', 'title', 'category', 'type', 'address'))
    bucket_rules: list[tuple[str, tuple[str, ...]]] = [
        ('museum', ('博物馆', '美术馆', '纪念馆', '科技馆', '展览馆', '非遗馆')),
        ('historic_block', ('历史文化街区', '文化街区', '古城', '古镇', '老街', '城墙', '遗址', '古迹')),
        ('lake_park', ('西湖', '湖', '公园', '湿地', '步道', '绿道', '滨河')),
        ('temple', ('寺', '庙', '塔', '书院')),
        ('theme_park', ('乐园', '动物园', '植物园', '海洋馆')),
        ('nature', ('山', '岛', '森林', '风景区', '风景名胜')),
        ('landmark', ('地标', '观景台')),
    ]
    for bucket, keywords in bucket_rules:
        if any(keyword in combined for keyword in keywords):
            return bucket
    return 'unknown'


def _is_generic_filler_name(name: str, anchor_city: str) -> bool:
    clean_name = _clean_attraction_name(name)
    city = _clean_city(anchor_city)
    if not clean_name:
        return True
    if any(token in clean_name for token in ('经典景点', '经典游览', '综合匹配')):
        return True
    generic_names = {
        f'{city}风景名胜区',
        f'{city}历史文化街区',
        f'{city}公园',
        f'{city}古城',
        f'{city}城市公园',
        f'{city}地标建筑',
        f'{city}非遗体验馆',
    }
    return bool(city and clean_name in generic_names)


def select_unique_day_pois(
    *,
    anchor_city: str,
    stage: str,
    candidates: list[dict[str, Any]],
    used_names: set[str],
    used_buckets_by_day: set[str],
    max_count: int,
    allow_repeat_must_visit: bool = True,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    local_identities: set[str] = set()
    selected_buckets = set(used_buckets_by_day)
    _ = stage
    for candidate in candidates:
        name = str(candidate.get('name') or candidate.get('title') or '').strip()
        if not name:
            continue
        must_visit = bool(candidate.get('must_visit')) or str(candidate.get('must_visit')).lower() == 'true'
        if _is_generic_filler_name(name, anchor_city) and not must_visit:
            continue
        identity = normalize_poi_identity(candidate)
        if identity and identity in local_identities:
            continue
        if identity and identity in used_names and not (must_visit and allow_repeat_must_visit):
            continue
        bucket = classify_poi_bucket(candidate)
        if bucket != 'unknown' and bucket in selected_buckets and not (must_visit and allow_repeat_must_visit):
            continue
        normalized = {key: str(value) for key, value in candidate.items() if value is not None}
        selected.append(normalized)
        if identity:
            local_identities.add(identity)
        if bucket != 'unknown':
            selected_buckets.add(bucket)
            used_buckets_by_day.add(bucket)
        if len(selected) >= max(0, max_count):
            break
    return selected


def _candidate_pois_for_day(
    *,
    anchor_city: str,
    stage: str,
    stage_day: int,
    ranked_pois: dict[str, list[dict[str, Any]]] | None,
    profile: dict[str, Any],
    route_context: dict[str, Any],
    used_attractions: set[str],
) -> list[dict[str, str]]:
    source_key = 'route_candidates' if stage == 'route' else 'destination_candidates'
    candidates: list[dict[str, str]] = []
    for item in (ranked_pois or {}).get(source_key, []) or []:
        name = str(item.get('name') or '').strip()
        if not name or name in used_attractions:
            continue
        if stage == 'route':
            item_stage_day = int(item.get('stage_day') or stage_day)
            stop_name = str(item.get('stop_name') or item.get('name') or '')
            if item_stage_day != stage_day and _clean_city(stop_name) != _clean_city(anchor_city):
                continue
        if not is_valid_attraction_poi(item):
            continue
        if not is_poi_in_planning_scope(item, anchor_city, {**route_context, 'stage': stage}, profile):
            continue
        candidates.append({key: str(value) for key, value in item.items() if value is not None})
    if len(candidates) < 3:
        for item in fetch_destination_poi_candidates(anchor_city, profile, {**route_context, 'stage': stage}):
            name = str(item.get('name') or '').strip()
            if not name or name in used_attractions or any(existing.get('name') == name for existing in candidates):
                continue
            if is_valid_attraction_poi(item) and is_poi_in_planning_scope(item, anchor_city, {**route_context, 'stage': stage}, profile):
                candidates.append({key: str(value) for key, value in item.items() if value is not None})
            if len(candidates) >= 6:
                break
    return candidates



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


def _normalize_weather_city(value: Any) -> str:
    return re.sub(r'\s+', '', str(value or '')).replace('市', '')


def find_weather_day_for_context(day_context: dict[str, Any], daily_weather: Any, fallback_index: int) -> dict[str, Any] | None:
    if not isinstance(daily_weather, list):
        return None
    weather_days = [item for item in daily_weather if isinstance(item, dict)]
    day = int(day_context.get('day') or fallback_index + 1)
    anchor_city = _normalize_weather_city(day_context.get('anchor_city') or day_context.get('destination') or '')
    if anchor_city:
        for item in weather_days:
            if int(item.get('day') or 0) == day and _normalize_weather_city(item.get('city')) == anchor_city:
                return item
        for item in weather_days:
            if int(item.get('day') or 0) == day and not _normalize_weather_city(item.get('city')):
                return item
        return None
    for item in weather_days:
        if int(item.get('day') or 0) == day:
            return item
    return None



def _build_trip_itinerary(
    request: TravelPlanRequest,
    profile: dict[str, Any],
    best_option: RouteOption,
    attractions: list[str],
    weather_hint: str,
    route_context: dict[str, Any],
    hotel_candidates: list[dict[str, str]] | None = None,
    food_candidates: list[dict[str, str]] | None = None,
    ranked_pois: dict[str, list[dict[str, Any]]] | None = None,
) -> list[TripDayPlan]:
    days = int(profile['duration_days'])
    destination = request.destination
    travel_style = profile['travel_style']
    preferences = request.preferences or ''
    attraction_pool = _pick_attractions(destination, attractions, preferences, max(days * 4, 8))
    must_visit_names = [str(item) for item in profile.get('must_visit_attractions') or [] if str(item).strip()]
    for name in reversed(must_visit_names):
        if name not in attraction_pool:
            attraction_pool.insert(0, name)
    attraction_pois = _resolve_attraction_pois(destination, attraction_pool[:min(max(days * 2, 5), 7)])
    scored_attraction_pois: list[dict[str, str]] = []
    for index, poi in enumerate(attraction_pois):
        enriched = dict(poi)
        enriched['route_order'] = str(index)
        enriched['estimated_minutes'] = str(_estimate_attraction_duration(enriched.get('name', ''), enriched.get('category'))[0])
        if enriched.get('name') in must_visit_names:
            enriched['must_visit'] = 'true'
            enriched['reason_hint'] = '用户指定必去'
        score = score_poi(enriched, profile, route_context)
        enriched['score'] = str(score['final_score'])
        enriched['reason'] = str(score['reason'])
        enriched['tags'] = '、'.join(str(tag) for tag in score.get('tags', [])) if isinstance(score.get('tags'), list) else ''
        scored_attraction_pois.append(enriched)
    attraction_pois = sorted(scored_attraction_pois or attraction_pois, key=lambda item: float(item.get('score') or 0), reverse=True)
    base_attraction_pois = list(attraction_pois)
    itinerary: list[TripDayPlan] = []
    total_drive_minutes = _parse_duration_minutes(best_option.duration)
    drive_segments = _estimate_drive_segments(total_drive_minutes, days)
    used_attractions: set[str] = set()
    used_poi_identities: set[str] = set()
    stage_counts = route_context.get('stage_counts') if isinstance(route_context.get('stage_counts'), dict) else {}
    stage_notes = [str(item) for item in stage_counts.get('stage_notes', [])] if isinstance(stage_counts, dict) else []
    weather_context = route_context.get('weather_context') if isinstance(route_context.get('weather_context'), dict) else {}
    daily_weather = weather_context.get('daily_weather') if isinstance(weather_context, dict) else []
    for day in range(1, days + 1):
        if '轻松' in travel_style or '老人' in preferences or '亲子' in preferences:
            pace_note = '节奏偏轻松，建议每个景点之间预留休息与机动时间。'
        else:
            pace_note = '节奏为常规游览强度，建议把核心景点放在上午与下午前段完成。'
        day_context = next((item for item in route_context.get('daily_plan_context', []) if item.get('day') == day), {})
        weather_day = find_weather_day_for_context(day_context, daily_weather, day - 1)
        stage = str(day_context.get('stage') or 'destination')
        stage_day = int(day_context.get('stage_day') or day)
        drive_today = int(day_context.get('daily_drive_minutes') or 0)
        available_visit_minutes = int(day_context.get('daily_available_visit_minutes') or 300)
        recommended_spots = max(1, min(3, int(day_context.get('recommended_spots') or 3)))
        anchor_city = str(day_context.get('anchor_city') or destination)
        route_segment = str(day_context.get('route_segment') or '')
        segment_data_source = str(day_context.get('segment_data_source') or 'fallback_estimated')
        transport_block = day_context.get('transport_block') if isinstance(day_context.get('transport_block'), dict) else None
        if stage == 'buffer':
            recommended_spots = min(recommended_spots, 1)
        effective_weather = _effective_weather_day(weather_context, weather_day)
        weather_badge = weather_badge_for_day(weather_context, weather_day)
        raw_weather_tags = [str(item) for item in (weather_day or {}).get('weather_tags', [])] if isinstance((weather_day or {}).get('weather_tags'), list) else []
        is_rain_weather = weather_badge in {'雨天', '预警'} or 'rain' in raw_weather_tags
        is_heat_weather = weather_badge == '高温' or 'heat' in raw_weather_tags or 'sun_exposure' in raw_weather_tags
        weather_summary = build_daily_weather_brief(weather_context, weather_day)
        daily_weather_adjustments = build_daily_weather_adjustments(weather_context, weather_day)
        day_candidate_pois = _candidate_pois_for_day(
            anchor_city=anchor_city,
            stage=stage,
            stage_day=stage_day,
            ranked_pois=ranked_pois,
            profile=profile,
            route_context=route_context,
            used_attractions=used_attractions,
        )
        candidate_pois = day_candidate_pois or base_attraction_pois
        if effective_weather:
            weather_score_context = {**route_context, **day_context, 'stage': stage, 'weather_day': effective_weather}
            candidate_pois = sorted(
                candidate_pois,
                key=lambda item: float(score_poi(dict(item), profile, weather_score_context).get('final_score') or 0),
                reverse=True,
            )
        used_buckets_by_day: set[str] = set()
        selected_pois = select_unique_day_pois(
            anchor_city=anchor_city,
            stage=stage,
            candidates=candidate_pois,
            used_names=used_poi_identities,
            used_buckets_by_day=used_buckets_by_day,
            max_count=recommended_spots,
        )
        morning_poi = selected_pois[0] if len(selected_pois) >= 1 else None
        afternoon_poi = selected_pois[1] if len(selected_pois) >= 2 else None
        evening_poi = selected_pois[2] if len(selected_pois) >= 3 else None
        if not drive_today:
            drive_today = drive_segments[min(day - 1, len(drive_segments) - 1)] if drive_segments else 0
        if stage == 'destination':
            drive_today = min(drive_today, 45)
        elif stage == 'buffer':
            drive_today = min(drive_today, 90)
        morning_name = (morning_poi or {}).get('name') or ''
        afternoon_name = (afternoon_poi or {}).get('name') or ''
        evening_name = (evening_poi or {}).get('name') or ''
        morning_addr = (morning_poi or {}).get('address') or ''
        afternoon_addr = (afternoon_poi or {}).get('address') or ''
        evening_addr = (evening_poi or {}).get('address') or ''
        morning_duration, morning_note = _estimate_attraction_duration(morning_name, (morning_poi or {}).get('category')) if morning_poi else (0, '')
        afternoon_duration, afternoon_note = _estimate_attraction_duration(afternoon_name, (afternoon_poi or {}).get('category')) if afternoon_poi else (0, '')
        evening_duration, evening_note = _estimate_attraction_duration(evening_name, (evening_poi or {}).get('category')) if evening_poi else (0, '')
        move_1 = _location_distance((morning_poi or {}).get('location'), (afternoon_poi or {}).get('location'))
        move_2 = _location_distance((afternoon_poi or {}).get('location'), (evening_poi or {}).get('location'))
        transfer_1 = 20 if morning_poi and afternoon_poi and move_1 is not None and move_1 < 0.03 else 40 if morning_poi and afternoon_poi else 0
        transfer_2 = 20 if afternoon_poi and evening_poi and move_2 is not None and move_2 < 0.03 else 35 if afternoon_poi and evening_poi else 0
        move_1_text = '两点距离较近，建议步行或短途接驳。' if transfer_1 == 20 else '两点之间建议预留 30-40 分钟交通切换。' if transfer_1 else ''
        move_2_text = '傍晚景点与下午景点衔接紧凑，可减少折返。' if transfer_2 == 20 else '晚间景点建议根据体力决定是否保留。' if transfer_2 else ''
        meal_hotel_notes = _build_meal_and_hotel_notes(anchor_city, morning_poi, afternoon_poi, evening_poi, None, None, day - 1)
        stage_score_context = {**route_context, **day_context, 'stage': stage, 'weather_day': effective_weather}
        day_attractions = []
        for poi in (morning_poi, afternoon_poi, evening_poi):
            if not poi:
                continue
            rescored = dict(poi)
            if rescored.get('name') in must_visit_names:
                rescored['must_visit'] = 'true'
            score = score_poi(rescored, profile, stage_score_context)
            rescored['reason'] = str(score['reason'])
            rescored['tags'] = '、'.join(str(tag) for tag in score.get('tags', [])) if isinstance(score.get('tags'), list) else str(rescored.get('tags') or '')
            day_attractions.append(rescored)
        day_reasons = [str(item.get('reason')) for item in day_attractions if item.get('reason') and '综合匹配' not in str(item.get('reason'))]
        if not day_reasons and day_attractions:
            day_reasons = [f'{anchor_city}当天候选与{route_segment or "当日路线"}和可游览时间匹配。']
        day_tags = _dedupe_text([tag for item in day_attractions for tag in str(item.get('tags') or '').split('、') if tag and tag != '综合匹配'])
        required_today = [str(item.get('name')) for item in day_attractions if str(item.get('must_visit')).lower() == 'true']
        meal_notes = [note for note in meal_hotel_notes if note.startswith(('午餐', '晚餐'))]
        hotel_note = next((note for note in meal_hotel_notes if note.startswith('住宿')), None)
        if stage == 'route':
            title = f'第{day}天：沿途阶段｜{route_segment or f"{request.origin} → {anchor_city}"}'
            stage_note = f'沿途阶段：以 {route_segment or anchor_city} 为主轴，围绕{anchor_city}安排停留、用餐和当天收尾区域。'
            route_segment = route_segment or f'{request.origin} → {anchor_city}'
        elif stage == 'buffer':
            title = f'第{day}天：机动/返程缓冲'
            stage_note = '机动缓冲：用于返程、补漏预约制景点或根据天气调整行程。'
            route_segment = route_segment or f'{destination}机动/返程缓冲'
            recommended_spots = min(recommended_spots, 1)
        else:
            title = f'第{day}天：目的地阶段｜{anchor_city}市内/周边'
            stage_note = f'目的地阶段：以{anchor_city}市内或近距离周边景点游览为主，避免继续使用跨城全程骨架。'
            route_segment = route_segment or f'{anchor_city}市内/周边'

        transport_mode = str((transport_block or {}).get('mode') or profile.get('intercity_mode') or request.travel_mode)
        transport_label = str((transport_block or {}).get('label') or transport_mode_label(transport_mode))
        transport_summary = str((transport_block or {}).get('summary') or '')
        if stage == 'route' and transport_mode not in {'driving', 'walking', 'bicycling'} and drive_today >= 120:
            transfer_start_hour, transfer_start_minute = 8, 0
            transfer_end_hour, transfer_end_minute = _shift_minutes(transfer_start_hour, transfer_start_minute, drive_today)
            transport_phrase = transport_summary or f'{transport_label}跨城转场约{_format_duration_minutes(drive_today)}'
            if morning_poi:
                morning_end_hour, morning_end_minute = _shift_minutes(transfer_end_hour, transfer_end_minute, morning_duration)
                morning = (
                    f'{_format_time(transfer_start_hour, transfer_start_minute)}-{_format_time(morning_end_hour, morning_end_minute)} '
                    f'先完成{transport_label}跨城抵达，{transport_phrase}；到达后出站接驳至 {morning_name}{f"（{morning_addr}）" if morning_addr else ""}，'
                    f'建议停留 {_format_duration_minutes(morning_duration)}，{morning_note}。'
                )
            else:
                morning_end_hour, morning_end_minute = _shift_minutes(transfer_end_hour, transfer_end_minute, 90)
                morning = (
                    f'{_format_time(transfer_start_hour, transfer_start_minute)}-{_format_time(morning_end_hour, morning_end_minute)} '
                    f'先完成{transport_label}跨城抵达，{transport_phrase}；抵达{anchor_city}后办理出站接驳、补给或入住，保留轻量休整。'
                )
            if afternoon_poi:
                afternoon_start_hour, afternoon_start_minute = _shift_minutes(morning_end_hour, morning_end_minute, transfer_1 + 40)
                afternoon_end_hour, afternoon_end_minute = _shift_minutes(afternoon_start_hour, afternoon_start_minute, afternoon_duration)
                afternoon = (
                    f'{_format_time(afternoon_start_hour, afternoon_start_minute)}-{_format_time(afternoon_end_hour, afternoon_end_minute)} '
                    f'前往 {afternoon_name}{f"（{afternoon_addr}）" if afternoon_addr else ""}，建议停留 {_format_duration_minutes(afternoon_duration)}；'
                    f'该段重点考虑与车站/上午景点的衔接效率。{move_1_text}'
                )
            else:
                afternoon_end_hour, afternoon_end_minute = _shift_minutes(morning_end_hour, morning_end_minute, 150)
                afternoon = f'下午保留为抵达、入住或休整时间，可在{anchor_city}核心区轻量散步，不强行增加景点。'
            if evening_poi:
                evening_start_hour, evening_start_minute = _shift_minutes(afternoon_end_hour, afternoon_end_minute, transfer_2 + 20)
                evening_end_hour, evening_end_minute = _shift_minutes(evening_start_hour, evening_start_minute, min(evening_duration, 120))
                evening = (
                    f'{_format_time(evening_start_hour, evening_start_minute)}-{_format_time(evening_end_hour, evening_end_minute)} '
                    f'视体力补充 {evening_name}{f"（{evening_addr}）" if evening_addr else ""}，建议停留 {_format_duration_minutes(min(evening_duration, 120))}；{evening_note}。{move_2_text}'
                )
            else:
                evening = '晚间以就近用餐和休息为主，避免长距离换乘后的疲劳。'
        elif stage == 'route' and request.travel_mode == 'driving' and drive_today >= 180:
            drive_start_hour, drive_start_minute = 8, 0
            drive_end_hour, drive_end_minute = _shift_minutes(drive_start_hour, drive_start_minute, drive_today)
            if morning_poi:
                morning_end_hour, morning_end_minute = _shift_minutes(drive_end_hour, drive_end_minute, morning_duration)
                morning = (
                    f'{_format_time(drive_start_hour, drive_start_minute)}-{_format_time(morning_end_hour, morning_end_minute)} '
                    f'先完成长距离抵达，预计驾驶约{max(1, round(drive_today / 60))}小时；抵达后游览 {morning_name}{f"（{morning_addr}）" if morning_addr else ""}，'
                    f'建议停留 {_format_duration_minutes(morning_duration)}，{morning_note}。'
                )
            else:
                morning_end_hour, morning_end_minute = _shift_minutes(drive_end_hour, drive_end_minute, 90)
                morning = (
                    f'{_format_time(drive_start_hour, drive_start_minute)}-{_format_time(morning_end_hour, morning_end_minute)} '
                    f'先完成长距离抵达，预计驾驶约{max(1, round(drive_today / 60))}小时；抵达{anchor_city}后办理停车、补给或入住，保留轻量休整。'
                )
            if afternoon_poi:
                afternoon_start_hour, afternoon_start_minute = _shift_minutes(morning_end_hour, morning_end_minute, transfer_1 + 40)
                afternoon_end_hour, afternoon_end_minute = _shift_minutes(afternoon_start_hour, afternoon_start_minute, afternoon_duration)
                afternoon = (
                    f'{_format_time(afternoon_start_hour, afternoon_start_minute)}-{_format_time(afternoon_end_hour, afternoon_end_minute)} '
                    f'前往 {afternoon_name}{f"（{afternoon_addr}）" if afternoon_addr else ""}，建议停留 {_format_duration_minutes(afternoon_duration)}；'
                    f'该段重点考虑与上午景点的衔接效率。{move_1_text}'
                )
            else:
                afternoon_end_hour, afternoon_end_minute = _shift_minutes(morning_end_hour, morning_end_minute, 150)
                afternoon = f'下午保留为抵达、入住或休整时间，可在{anchor_city}核心区轻量散步，不强行增加景点。'
            if evening_poi:
                evening_start_hour, evening_start_minute = _shift_minutes(afternoon_end_hour, afternoon_end_minute, transfer_2 + 20)
                evening_end_hour, evening_end_minute = _shift_minutes(evening_start_hour, evening_start_minute, min(evening_duration, 120))
                evening = (
                    f'{_format_time(evening_start_hour, evening_start_minute)}-{_format_time(evening_end_hour, evening_end_minute)} '
                    f'视体力补充 {evening_name}{f"（{evening_addr}）" if evening_addr else ""}，建议停留 {_format_duration_minutes(min(evening_duration, 120))}；{evening_note}。{move_2_text}'
                )
            else:
                evening = '晚间以就近用餐和休息为主，避免长距离驾驶后的路途疲劳。'
        else:
            morning_start_hour, morning_start_minute = 8, 30
            if morning_poi:
                morning_end_hour, morning_end_minute = _shift_minutes(morning_start_hour, morning_start_minute, morning_duration)
                morning = (
                    f'{_format_time(morning_start_hour, morning_start_minute)}-{_format_time(morning_end_hour, morning_end_minute)} '
                    f'上午主攻 {morning_name}{f"（{morning_addr}）" if morning_addr else ""}，建议停留 {_format_duration_minutes(morning_duration)}；'
                    f'{morning_note}，如为热门博物馆/古迹类景点建议提前预约。'
                )
            else:
                morning_end_hour, morning_end_minute = _shift_minutes(morning_start_hour, morning_start_minute, 120)
                morning = f'09:30-11:30 熟悉{anchor_city}核心区域，保留自由活动或预约核验时间，不强行增加景点。'
            if afternoon_poi:
                afternoon_start_hour, afternoon_start_minute = _shift_minutes(morning_end_hour, morning_end_minute, transfer_1 + 60)
                afternoon_end_hour, afternoon_end_minute = _shift_minutes(afternoon_start_hour, afternoon_start_minute, afternoon_duration)
                afternoon = (
                    f'{_format_time(afternoon_start_hour, afternoon_start_minute)}-{_format_time(afternoon_end_hour, afternoon_end_minute)} '
                    f'下午转场至 {afternoon_name}{f"（{afternoon_addr}）" if afternoon_addr else ""}，建议停留 {_format_duration_minutes(afternoon_duration)}；'
                    f'优先把核心看点、主展线或主要游览段放在这一时段完成。{move_1_text}'
                )
            else:
                afternoon_end_hour, afternoon_end_minute = _shift_minutes(morning_end_hour, morning_end_minute, 180)
                afternoon = f'下午保留为抵达、入住、休整或自由活动，可在{anchor_city}就近轻量散步。'
            if evening_poi:
                evening_start_hour, evening_start_minute = _shift_minutes(afternoon_end_hour, afternoon_end_minute, transfer_2 + 20)
                evening_end_hour, evening_end_minute = _shift_minutes(evening_start_hour, evening_start_minute, min(evening_duration, 120))
                evening = (
                    f'{_format_time(evening_start_hour, evening_start_minute)}-{_format_time(evening_end_hour, evening_end_minute)} '
                    f'傍晚安排 {evening_name}{f"（{evening_addr}）" if evening_addr else ""}，建议停留 {_format_duration_minutes(min(evening_duration, 120))}；'
                    f'{evening_note}。{move_2_text}'
                )
            else:
                evening = '晚间以就近用餐、整理行李和休息为主，根据体力决定是否自由活动。'
        if stage == 'destination':
            morning = morning.replace('上午主攻', f'目的地第{stage_day}天上午主攻')
            afternoon = afternoon.replace('下午转场至', '下午在目的地内转场至')
            evening = evening.replace('傍晚安排', '晚间就近安排')
            if effective_weather and is_rain_weather:
                morning = morning.replace('目的地第', '雨天优先室内：目的地第')
                afternoon = afternoon.replace('下午在目的地内转场至', '下午优先转场至室内或遮蔽条件较好的')
            elif effective_weather and is_heat_weather:
                morning = morning.replace('目的地第', '晴热早段优先户外：目的地第')
                afternoon = f'中午安排室内景点、午餐或休整，避开正午户外暴晒；{afternoon}'
            elif effective_weather and effective_weather.get('outdoor_suitability') == 'good':
                morning = morning.replace('目的地第', '天气适合室外：目的地第')
        elif stage == 'buffer':
            morning = f'09:30-11:30 保留机动时间，可补充 {morning_name} 或处理返程/换乘安排。' if morning_poi else '09:30-11:30 保留机动时间，处理返程、换乘或补漏预约事项。'
            afternoon = '下午根据天气、体力和返程时间自由调整，不再强行增加远距离景点。'
            evening = '晚间以就近用餐、整理行李和休息为主。'
        if effective_weather and is_rain_weather:
            if '带伞/雨衣' not in morning:
                morning = f'雨天带伞/雨衣并注意防滑，优先室内或遮蔽点位；{morning}'
            if '湖边、公园、步道压缩游览' not in afternoon:
                afternoon = f'下午优先室内或遮蔽点位，湖边、公园、步道压缩游览；{afternoon}'
        elif effective_weather and is_heat_weather:
            if '避开正午户外暴晒' not in afternoon:
                afternoon = f'中午安排室内景点、午餐或休整，避开正午户外暴晒；{afternoon}'
            if '补水' not in evening:
                evening = f'傍晚再补充户外点位并注意补水；{evening}'
        weather_data_source = str(
            ((weather_day or {}).get('data_source') or weather_context.get('data_source') or 'fallback') if weather_day else 'fallback'
        )
        fallback_weather_note = ''
        if weather_data_source != 'tencent_maps':
            weather_strategy = ''
            weather_summary = ''
            daily_weather_adjustments = []
            fallback_weather_note = '天气策略：天气待确认，出行前查看实时天气；本日不做确定性天气重排。'
        else:
            weather_strategy = str((weather_day or {}).get('strategy') or '按实时天气调整室内外景点顺序。')
        weather_label = ''
        if weather_day:
            if weather_data_source != 'tencent_maps':
                weather_label = ''
            else:
                weather_label = f"当天天气：{weather_day.get('city', anchor_city)} {weather_day.get('weather', '天气待确认')}，{weather_day.get('temperature', '温度待确认')}。"
        generated_weather_tips = build_weather_tips(weather_day, data_source=weather_data_source) if weather_day else {}

        def structured_weather_list(key: str) -> list[str]:
            explicit = (weather_day or {}).get(key, [])
            items = explicit if isinstance(explicit, list) else []
            generated = generated_weather_tips.get(key, []) if isinstance(generated_weather_tips.get(key), list) else []
            return _dedupe_text([str(item) for item in [*items, *generated] if str(item).strip()])

        weather_tips = structured_weather_list('weather_tips')
        packing_tips = structured_weather_list('packing_tips')
        weather_tags = structured_weather_list('weather_tags')
        if weather_data_source != 'tencent_maps':
            weather_tips = ['建议出行前查看实时天气，不做确定性天气重排。']
            packing_tips = _dedupe_text(packing_tips or ['天气待确认，保留雨具、防晒和补水用品作为备选'])
        total_visit_minutes = morning_duration + afternoon_duration + min(evening_duration, 120)
        visit_note = (
            f'当日景点建议停留总时长约 {_format_duration_minutes(total_visit_minutes)}。'
            if total_visit_minutes
            else '当天不强行安排固定景点，以抵达、休整和自由活动为主。'
        )
        if len(day_attractions) >= 3:
            transfer_note = f'景点转场参考：上午到下午约预留 {transfer_1} 分钟，下午到傍晚约预留 {transfer_2} 分钟。'
        elif len(day_attractions) == 2:
            transfer_note = f'景点转场参考：两个景点之间约预留 {transfer_1 or 30} 分钟，优先减少折返。'
        else:
            transfer_note = '景点转场参考：当天景点较少，优先减少折返并保留体力。'
        if transport_block and transport_mode not in {'driving', 'walking', 'bicycling'}:
            route_time_note = f'当日路线段：{route_segment}，{transport_summary or f"{transport_label}跨城转场约{_format_duration_minutes(drive_today)}"}。'
        else:
            route_time_note = f'当日路线段：{route_segment}，{"预计" if segment_data_source != "tencent_maps" else "腾讯地图"}行驶/转场约{_format_duration_minutes(drive_today)}。'
        notes = [
            stage_note,
            pace_note,
            weather_label,
            f'天气策略：{weather_strategy}' if weather_strategy else '',
            fallback_weather_note,
            *daily_weather_adjustments,
            visit_note,
            transfer_note,
            route_time_note,
            f'当天包含用户指定途经点/必去景点：{"、".join(required_today)}。' if required_today else '',
            *stage_notes,
        ]
        notes = _dedupe_text([note for note in notes if note])
        for used_name in (morning_name, afternoon_name, evening_name):
            if used_name:
                used_attractions.add(used_name)
        for poi in day_attractions:
            identity = normalize_poi_identity(poi)
            if identity:
                used_poi_identities.add(identity)
        itinerary.append(
            TripDayPlan(
                day=day,
                title=title,
                stage=stage,
                route_segment=route_segment,
                anchor_city=anchor_city,
                segment_data_source=segment_data_source,
                drive_time=_format_duration_minutes(drive_today),
                visit_time=_format_duration_minutes(available_visit_minutes),
                weather_strategy=weather_strategy,
                weather_summary=weather_summary,
                weather_adjustments=daily_weather_adjustments,
                weather_badge=weather_badge,
                weather_tips=weather_tips,
                packing_tips=packing_tips,
                weather_tags=weather_tags,
                transport_block=transport_block,
                morning=morning,
                afternoon=afternoon,
                evening=evening,
                attractions=[
                    {
                        'name': item.get('name', ''),
                        'address': item.get('address', ''),
                        'category': item.get('category', ''),
                        'reason': item.get('reason', '') or ('用户指定必去，已纳入当日行程。' if str(item.get('must_visit')).lower() == 'true' else ''),
                        'tags': item.get('tags', ''),
                        'must_visit': 'true' if str(item.get('must_visit')).lower() == 'true' else 'false',
                    }
                    for item in day_attractions[:recommended_spots]
                ],
                meals=meal_notes,
                hotel_hint=hotel_note,
                recommendation_reasons=_dedupe_text(day_reasons)[:3],
                tags=_dedupe_text(day_tags)[:5],
                notes=notes,
            )
        )
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
    destination = request.destination
    attraction_recommendations = [item for item in attractions if destination in item or any(city_hint in item for city_hint in _CITY_HINTS)]
    if not attraction_recommendations:
        attraction_recommendations = [
            f'{destination}博物馆',
            f'{destination}历史文化街区',
            f'{destination}城市公园',
        ]
    accommodation_suggestion = '住宿按每日收尾景点就近选择，优先住在核心景点、老城区商圈或交通换乘方便区域，减少第二天折返。'
    transportation_suggestion = _build_transportation_suggestions(request, best_option)
    transportation_suggestion = transportation_suggestion[:3]
    travel_tips = [
        f'{duration_days}天行程按“抵达适应—经典景点深度游—返程收尾”拆分，避免每天排满。',
        '行程重点围绕经典景点的停留时长、景点间距离和天气适配来组织。',
        '餐厅优先放在上午/下午景点之间，酒店优先贴近当天最后一个景点或换乘方便商圈。',
        '热门博物馆、古迹、演出和景区门票建议提前预约；每天至少保留30-60分钟机动时间。',
        f'天气提示：{weather_hint}',
    ]
    if request.waypoints:
        travel_tips.append(f'途经点可作为去程或返程中途停留：{"、".join(w.name for w in request.waypoints)}。')
    overview = f'这是一个面向真实游玩的{destination}{duration_days}天行程规划，核心围绕经典景点的实际游览时长、景点间距离和每日天气变化来安排先后顺序；优先保证景点本身的完整体验，而不是以餐厅和住宿作为主线。'
    budget_summary = '已移除预算建议，当前重点保留景点、交通和天气策略。'
    return overview, budget_summary, transportation_suggestion, weather_hint, attraction_recommendations, travel_tips, accommodation_suggestion



def compose_travel_plan(
    *,
    request: TravelPlanRequest,
    profile: dict[str, Any],
    route_options: list[RouteOption],
    data_source: str,
    route_error: str | None,
    location_debug: dict[str, Any],
    route_context: dict[str, Any],
    poi_candidates: dict[str, Any],
    weather_context: dict[str, Any],
    ranked_pois: dict[str, list[dict[str, Any]]],
    daily_itinerary: list[TripDayPlan] | None = None,
    memory_store_override: RedisMemoryStore | None = None,
) -> TravelPlanResponse:
    conversation_id = request.conversation_id or str(uuid4())
    intent = _classify_intent(f"{request.origin} {request.destination} {request.preferences or ''} {request.source_query or ''}")
    scenario = _classify_scenario(request)
    preferences = _extract_preferences(request)
    active_memory_store = memory_store_override or memory_store
    user_preferences, short_term = _load_and_update_memory(active_memory_store, conversation_id, request, profile, preferences)
    if not route_options:
        route_options = _fallback_routes(request, scenario, 'empty_state')
        data_source = 'fallback'
        route_error = route_error or 'Route options missing in graph state'
    best_option = _choose_best_option(route_options, request)
    stage_counts = route_context.get('stage_counts') if isinstance(route_context.get('stage_counts'), dict) else {}
    if stage_counts:
        profile = dict(profile)
        profile['duration_days'] = int(stage_counts.get('total_days') or profile.get('duration_days') or 1)
        profile['route_days'] = int(stage_counts.get('route_days') or 0)
        profile['destination_days'] = int(stage_counts.get('destination_days') or 0)
        profile['buffer_days'] = int(stage_counts.get('buffer_days') or 0)
        profile['stage_plan_mode'] = stage_counts.get('stage_plan_mode') or profile.get('stage_plan_mode')
        profile['stage_notes'] = stage_counts.get('stage_notes', [])
    route_issues = _validate_route_reasonableness(best_option, request)
    route_issues.extend(str(item) for item in route_context.get('warnings', []))
    weather_hint = _weather_hint_from_context(request.destination, weather_context)
    route_stop_names = [str(item.get('name')) for item in poi_candidates.get('route_stops', []) if item.get('name')]
    ranked_route_names = [str(item.get('name')) for item in ranked_pois.get('route_candidates', [])[:6] if item.get('name')]
    ranked_destination_names = [str(item.get('name')) for item in ranked_pois.get('destination_candidates', [])[:8] if item.get('name')]
    attraction_recommendations = _dedupe_text([*ranked_route_names, *ranked_destination_names, *route_stop_names])
    if not attraction_recommendations:
        attraction_recommendations = [f'{request.destination}博物馆', f'{request.destination}城市公园', f'{request.destination}历史文化街区']
    hotel_candidates = poi_candidates.get('hotel_candidates', [])
    food_candidates = poi_candidates.get('food_candidates', [])
    quality_note = '; '.join(route_issues) if route_issues else None
    summary = _build_summary(request, best_option, scenario, data_source, quality_note, weather_hint, attraction_recommendations, hotel_candidates, food_candidates)
    trip_overview, budget_summary, transportation_suggestion, weather_hint, attraction_recommendations, travel_tips, accommodation_suggestion = _build_trip_content(
        request,
        profile,
        best_option,
        weather_hint,
        attraction_recommendations,
        hotel_candidates,
        food_candidates,
    )
    if daily_itinerary is None:
        daily_itinerary = build_daily_itinerary(request, profile, route_context, ranked_pois, route_options, weather_hint, hotel_candidates, food_candidates)
    weather_plan_summary = build_weather_plan_summary(weather_context, daily_itinerary)
    if weather_plan_summary.get('weather_overview'):
        summary = f'{summary}\n天气融入：{weather_plan_summary["weather_overview"]}'
        trip_overview = f'{trip_overview} 天气融入：{weather_plan_summary["weather_overview"]}'
    scheduled_names = {str(item.get('name')) for day in daily_itinerary for item in day.attractions if item.get('name')}
    must_visit_attractions = [str(item) for item in profile.get('must_visit_attractions') or [] if str(item).strip()]
    unscheduled_waypoints = [name for name in must_visit_attractions if name not in scheduled_names]
    if unscheduled_waypoints:
        travel_tips.append(f'以下用户指定地点未能放入每日主行程，建议作为备选或延长停留：{"、".join(unscheduled_waypoints)}。')
    history = [
        ConversationTurn(user_input=str(item.get('user_input') or ''), assistant_output=str(item.get('assistant_output') or ''))
        for item in short_term[-10:]
        if isinstance(item, dict)
    ]
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
        trip_type=str(profile.get('trip_type') or 'destination_trip'),
        route_total_duration=str(route_context.get('route_total_duration') or best_option.duration),
        route_total_distance=str(route_context.get('route_total_distance') or best_option.distance),
        trip_overview=trip_overview,
        duration_days=int(profile.get('duration_days') or 3),
        budget_estimate=budget_summary,
        accommodation_suggestion=accommodation_suggestion,
        transportation_suggestion=transportation_suggestion,
        weather_hint=weather_hint,
        weather_overview=str(weather_plan_summary.get('weather_overview') or ''),
        weather_adjustments=[str(item) for item in weather_plan_summary.get('weather_adjustments', [])],
        packing_summary=[str(item) for item in weather_plan_summary.get('packing_summary', [])],
        attraction_recommendations=attraction_recommendations,
        hotel_candidates=hotel_candidates,
        food_candidates=food_candidates,
        daily_itinerary=daily_itinerary,
        travel_tips=travel_tips,
        route_steps=best_option.steps,
        route_options=route_options,
        recommendation_reasons=best_option.reasons,
        user_preferences=user_preferences,
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
                'trip_type': profile.get('trip_type'),
                'interest_tags': profile.get('interest_tags', []),
                'avoid_tags': profile.get('avoid_tags', []),
                'pace': profile.get('pace'),
                'route_days': profile.get('route_days'),
                'destination_days': profile.get('destination_days'),
                'buffer_days': profile.get('buffer_days'),
                'stage_plan_mode': profile.get('stage_plan_mode'),
                'stage_notes': profile.get('stage_notes', []),
                'duration_source': profile.get('duration_source'),
                **_response_debug_metadata(),
            },
            'location_debug': location_debug,
            'stage_segments': route_context.get('stage_segments', []),
            'route_stops': poi_candidates.get('route_stops', []),
            'poi_candidates': poi_candidates,
            'ranked_pois': ranked_pois,
            'waypoint_details': profile.get('waypoint_details', []),
            'must_visit_attractions': must_visit_attractions,
            'waypoint_order_mode': profile.get('waypoint_order_mode', 'unspecified'),
            'unscheduled_waypoints': unscheduled_waypoints,
            'trip_profile': profile,
            'route_context': route_context,
            'weather_context': weather_context,
            'weather_plan_summary': weather_plan_summary,
            'weather_hint': weather_hint,
            'attractions': attraction_recommendations,
            'hotel_candidates': hotel_candidates,
            'food_candidates': food_candidates,
        },
        data_source=data_source,
        confidence=confidence,
        route_error=route_error,
    )


def build_travel_plan(request: TravelPlanRequest, memory_store_override: RedisMemoryStore | None = None) -> TravelPlanResponse:
    conversation_id = request.conversation_id or str(uuid4())
    intent = _classify_intent(f"{request.origin} {request.destination} {request.preferences or ''} {request.source_query or ''}")
    scenario = _classify_scenario(request)
    preferences = _extract_preferences(request)
    active_memory_store = memory_store_override or memory_store
    profile = _extract_trip_profile(request)
    route_options, data_source, route_error, location_debug = fetch_route_options(request, profile)
    best_option = _choose_best_option(route_options, request)
    route_context = build_route_context(request, profile, route_options, data_source, location_debug)
    stage_counts = route_context.get('stage_counts') if isinstance(route_context.get('stage_counts'), dict) else {}
    if stage_counts:
        profile['duration_days'] = int(stage_counts.get('total_days') or profile.get('duration_days') or 1)
        profile['route_days'] = int(stage_counts.get('route_days') or 0)
        profile['destination_days'] = int(stage_counts.get('destination_days') or 0)
        profile['buffer_days'] = int(stage_counts.get('buffer_days') or 0)
        profile['stage_plan_mode'] = stage_counts.get('stage_plan_mode') or profile.get('stage_plan_mode')
        profile['stage_notes'] = stage_counts.get('stage_notes', [])
    profile['trip_type'] = decide_trip_type({**profile, 'origin': request.origin, 'destination': request.destination, 'travel_mode': request.travel_mode, 'source_text': request.source_query or request.preferences or ''}, route_context)
    user_preferences, short_term = _load_and_update_memory(active_memory_store, conversation_id, request, profile, preferences)
    route_issues = _validate_route_reasonableness(best_option, request)
    route_issues.extend(str(item) for item in route_context.get('warnings', []))
    destination_point = location_debug.get('destination_point')
    origin_point = location_debug.get('origin_point')
    weather_hint = _fetch_weather_hint(request.destination, destination_point)
    poi_candidates = fetch_poi_candidates(request, profile, route_context, location_debug)
    weather_context = _build_weather_context_for_plan(
        destination=request.destination,
        route_stops=poi_candidates.get('route_stops', []),
        days=int(profile.get('duration_days') or 3),
        location_debug=location_debug,
        daily_plan_context=route_context.get('daily_plan_context', []),
    )
    route_context['weather_context'] = weather_context
    weather_hint = _weather_hint_from_context(request.destination, weather_context, weather_hint)
    ranked_pois = rank_poi_candidates(poi_candidates, profile, route_context)
    route_stop_names = [str(item.get('name')) for item in poi_candidates.get('route_stops', []) if item.get('name')]
    ranked_route_names = [str(item.get('name')) for item in ranked_pois.get('route_candidates', [])[:6] if item.get('name')]
    ranked_destination_names = [str(item.get('name')) for item in ranked_pois.get('destination_candidates', [])[:8] if item.get('name')]
    attraction_recommendations = _fetch_along_route_attractions(origin_point, destination_point, _infer_region_from_text(request.destination) or request.destination)
    attraction_recommendations = _dedupe_text([*ranked_route_names, *ranked_destination_names, *attraction_recommendations, *route_stop_names])
    hotel_candidates = _search_hotels_for_city(request.destination, destination_point)
    food_candidates = _search_foods_for_location(request.destination, destination_point)
    if not hotel_candidates:
        hotel_candidates = poi_candidates.get('hotel_candidates', [])
    if not food_candidates:
        food_candidates = poi_candidates.get('food_candidates', [])
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
    daily_itinerary = _build_trip_itinerary(request, profile, best_option, attraction_recommendations, weather_hint, route_context, hotel_candidates, food_candidates, ranked_pois)
    weather_plan_summary = build_weather_plan_summary(weather_context, daily_itinerary)
    if weather_plan_summary.get('weather_overview'):
        summary = f'{summary}\n天气融入：{weather_plan_summary["weather_overview"]}'
        trip_overview = f'{trip_overview} 天气融入：{weather_plan_summary["weather_overview"]}'
    scheduled_names = {str(item.get('name')) for day in daily_itinerary for item in day.attractions if item.get('name')}
    must_visit_attractions = [str(item) for item in profile.get('must_visit_attractions') or [] if str(item).strip()]
    unscheduled_waypoints = [name for name in must_visit_attractions if name not in scheduled_names]
    if unscheduled_waypoints:
        travel_tips.append(f'以下用户指定地点未能放入每日主行程，建议作为备选或延长停留：{"、".join(unscheduled_waypoints)}。')
    history = [
        ConversationTurn(user_input=str(item.get('user_input') or ''), assistant_output=str(item.get('assistant_output') or ''))
        for item in short_term[-10:]
        if isinstance(item, dict)
    ]
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
        trip_type=str(profile.get('trip_type') or 'destination_trip'),
        route_total_duration=str(route_context.get('route_total_duration') or best_option.duration),
        route_total_distance=str(route_context.get('route_total_distance') or best_option.distance),
        trip_overview=trip_overview,
        duration_days=int(profile['duration_days']),
        budget_estimate=budget_summary,
        accommodation_suggestion=accommodation_suggestion,
        transportation_suggestion=transportation_suggestion,
        weather_hint=weather_hint,
        weather_overview=str(weather_plan_summary.get('weather_overview') or ''),
        weather_adjustments=[str(item) for item in weather_plan_summary.get('weather_adjustments', [])],
        packing_summary=[str(item) for item in weather_plan_summary.get('packing_summary', [])],
        attraction_recommendations=attraction_recommendations,
        hotel_candidates=hotel_candidates,
        food_candidates=food_candidates,
        daily_itinerary=daily_itinerary,
        travel_tips=travel_tips,
        route_steps=best_option.steps,
        route_options=route_options,
        recommendation_reasons=best_option.reasons,
        user_preferences=user_preferences,
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
                'trip_type': profile.get('trip_type'),
                'interest_tags': profile.get('interest_tags', []),
                'avoid_tags': profile.get('avoid_tags', []),
                'pace': profile.get('pace'),
                'route_days': profile.get('route_days'),
                'destination_days': profile.get('destination_days'),
                'buffer_days': profile.get('buffer_days'),
                'stage_plan_mode': profile.get('stage_plan_mode'),
                'stage_notes': profile.get('stage_notes', []),
                'duration_source': profile.get('duration_source'),
                **_response_debug_metadata(),
            },
            'location_debug': location_debug,
            'stage_segments': route_context.get('stage_segments', []),
            'route_stops': poi_candidates.get('route_stops', []),
            'poi_candidates': poi_candidates,
            'ranked_pois': ranked_pois,
            'waypoint_details': profile.get('waypoint_details', []),
            'must_visit_attractions': must_visit_attractions,
            'waypoint_order_mode': profile.get('waypoint_order_mode', 'unspecified'),
            'unscheduled_waypoints': unscheduled_waypoints,
            'trip_profile': profile,
            'route_context': route_context,
            'weather_context': weather_context,
            'weather_plan_summary': weather_plan_summary,
            'weather_hint': weather_hint,
            'attractions': attraction_recommendations,
            'hotel_candidates': hotel_candidates,
            'food_candidates': food_candidates,
        },
        data_source=data_source,
        confidence=confidence,
        route_error=route_error,
    )
