from __future__ import annotations

import re
from typing import Any

from travel_agent.core.config import get_settings
from travel_agent.core.logging import get_logger
from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.intent_service import extract_locations
from travel_agent.services.request_builder import build_travel_request
from travel_agent.tools.tencent_webservice_client import TencentWebServiceClient

settings = get_settings()
logger = get_logger(__name__)
_client = TencentWebServiceClient()

_POI_BLOCKED_NAME_HINTS = ('本地生活', '服务中心', '营销中心', '售楼处', '写字楼', '商务中心', '公寓', '住宅', '小区', '家电', '银行', '公司', '中心店', '旗舰店', '专卖店', '便利店', '超市')
_POI_BLOCKED_CATEGORY_HINTS = ('房地产', '公司企业', '生活服务', '购物', '金融', '汽车服务', '房产小区', '商务住宅')
_SCENIC_ALLOWED_HINTS = ('景区', '风景区', '名胜', '古迹', '古镇', '古城', '城墙', '博物馆', '纪念馆', '美术馆', '科技馆', '文化馆', '公园', '湿地', '乐园', '寺', '塔', '湖', '山', '步道', '遗址', '街区')
_FOOD_ALLOWED_HINTS = ('餐厅', '饭店', '小吃', '面馆', '火锅', '烧烤', '咖啡', '茶馆', '酒楼', '美食', '甜品', '早餐', '夜宵')
_HOTEL_ALLOWED_HINTS = ('酒店', '宾馆', '民宿', '客栈', '旅舍', '公寓酒店', '度假酒店')


def _debug_payload(debug: dict[str, Any]) -> dict[str, Any]:
    if settings.debug:
        return debug
    keep = {'keyword', 'anchor', 'anchor_point', 'city', 'reason', 'final_total', 'final_count', 'hotel_count', 'food_count', 'poi_count'}
    return {key: value for key, value in debug.items() if key in keep}


def poi_matches_bucket(item: dict[str, str], keyword: str) -> bool:
    name = item.get('name', '')
    category = item.get('category', '')
    combined = f'{name} {category}'
    if any(token in combined for token in _POI_BLOCKED_NAME_HINTS) or any(token in category for token in _POI_BLOCKED_CATEGORY_HINTS):
        return False
    if keyword == '景点':
        return any(token in combined for token in _SCENIC_ALLOWED_HINTS)
    if keyword == '餐厅':
        return any(token in combined for token in _FOOD_ALLOWED_HINTS)
    if keyword == '酒店':
        return any(token in combined for token in _HOTEL_ALLOWED_HINTS)
    return True


def _extract_poi_list(payload: dict | None, limit: int = 8, keyword: str | None = None) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        return []
    candidates = payload.get('data') or payload.get('result') or []
    if isinstance(candidates, dict):
        candidates = [candidates]
    elif not isinstance(candidates, list):
        candidates = []
    results: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get('title') or item.get('name') or '').strip()
        if not name:
            continue
        location = item.get('location') if isinstance(item.get('location'), dict) else {}
        lat = location.get('lat')
        lng = location.get('lng')
        poi = {
            'id': str(item.get('id') or item.get('uid') or '').strip(),
            'name': name,
            'address': str(item.get('address') or '').strip(),
            'category': str(item.get('category') or '').strip(),
            'location': f'{lat},{lng}' if lat is not None and lng is not None else '',
        }
        if keyword is None or poi_matches_bucket(poi, keyword):
            results.append(poi)
    return results[:limit]


def _extract_location_point(payload: dict | None) -> tuple[str | None, dict[str, object]]:
    debug: dict[str, object] = {'source': None}
    if not isinstance(payload, dict):
        return None, debug
    result = payload.get('result') if isinstance(payload.get('result'), dict) else payload
    if not isinstance(result, dict):
        return None, debug
    location = result.get('location') if isinstance(result.get('location'), dict) else {}
    lat = location.get('lat')
    lng = location.get('lng')
    if lat is not None and lng is not None:
        debug['source'] = 'location'
        return f'{lat},{lng}', debug
    return None, debug


def _normalize_anchor_candidate(value: str) -> str:
    anchor = value.strip('，。；,！？:： ').strip()
    anchor = re.sub(r'^(帮我|请|请帮我|推荐|查一下|查查|找一下|找找|看看|想找|我想找|我想看|推荐下)', '', anchor).strip()
    anchor = re.sub(r'(附近|周边|周围|旁边|临近|靠近)$', '', anchor).strip()
    anchor = re.sub(r'^(的|在|去|到)', '', anchor).strip()
    anchor = re.sub(r'(酒店|餐厅|景点|美食|商场|公园|博物馆|民宿|宾馆|饭店)+$', '', anchor).strip('的')
    return anchor.strip()


def _extract_nearby_anchor_text(question: str) -> str | None:
    for pattern in (r'(?P<anchor>[^，。；,、/\s]{2,24})(?:附近|周边|周围|旁边|临近|靠近)', r'(?:附近|周边|周围|旁边|临近|靠近)(?:的)?(?P<anchor>[^，。；,、/\s]{2,24})'):
        match = re.search(pattern, question)
        if match:
            anchor = _normalize_anchor_candidate(match.group('anchor'))
            if anchor:
                return anchor
    return None


def resolve_query_city(request: ChatRequest) -> str:
    parsed_origin, parsed_destination = extract_locations(request.question)
    if parsed_destination:
        return parsed_destination
    if parsed_origin and any(keyword in request.question for keyword in ('天气', '气温', '下雨', '降雨', '穿搭')):
        return parsed_origin
    current_anchor = _extract_nearby_anchor_text(request.question)
    if current_anchor:
        return current_anchor
    if request.force_current_anchor:
        return '目标城市'
    for value in (request.destination, request.origin):
        text = (value or '').strip()
        if text:
            return text
    return '目标城市'


def resolve_nearby_anchor(question: str, city: str, forced_anchor: str | None = None) -> tuple[str, str | None, dict[str, object]]:
    anchor = _normalize_anchor_candidate((forced_anchor or _extract_nearby_anchor_text(question) or city).strip()) or city
    if anchor == '目标城市':
        origin, destination = extract_locations(question)
        anchor = destination or origin or city
    debug: dict[str, object] = {'anchor': anchor, 'mode': None, 'attempts': []}
    if settings.tencent_maps_key:
        for attempt_type, call in (
            ('suggestion', lambda: _client.suggestion(anchor, region=city)),
            ('geocoder', lambda: _client.smart_geocoder(anchor, region=city)),
            ('place_search', lambda: _client.place_search_by_region(anchor, city, page_size=5, page_index=1)),
        ):
            try:
                payload = call()
                if attempt_type == 'place_search':
                    place_items = _extract_poi_list(payload, 5, '景点')
                    debug['attempts'].append({'type': attempt_type, 'count': len(place_items)})
                    if place_items and place_items[0].get('location'):
                        debug['mode'] = 'landmark'
                        return anchor, place_items[0]['location'], _debug_payload(debug)
                else:
                    point, point_debug = _extract_location_point(payload)
                    debug['attempts'].append({'type': attempt_type, 'debug': point_debug})
                    if point:
                        debug['mode'] = 'poi' if attempt_type == 'suggestion' else 'address'
                        return anchor, point, _debug_payload(debug)
            except Exception as exc:
                logger.exception('Nearby anchor resolution failed')
                debug['attempts'].append({'type': attempt_type, 'error': exc.__class__.__name__})
    debug['mode'] = 'city_fallback'
    return anchor, None, _debug_payload(debug)


def search_nearby_category(keyword: str, anchor: str, anchor_point: str | None, city: str, radius: int = 1500) -> tuple[list[dict[str, str]], dict[str, object]]:
    debug: dict[str, object] = {'keyword': keyword, 'anchor': anchor, 'anchor_point': anchor_point, 'city': city, 'radius_candidates': []}
    if not settings.tencent_maps_key:
        debug['reason'] = 'missing_key'
        return [], _debug_payload(debug)
    query_terms = [keyword]
    if keyword == '酒店':
        query_terms += ['宾馆', '民宿', '度假酒店']
    elif keyword == '餐厅':
        query_terms += ['美食', '小吃', '本地菜', '特色餐', '饭店']
    elif keyword == '景点':
        query_terms += ['公园', '博物馆', '地标', '商场']
    regions: list[tuple[str, str | None]] = []
    if anchor_point:
        regions.append((anchor, anchor_point))
    regions.append((city, None))
    radius_candidates = [radius, max(radius * 2, 2500), max(radius * 3, 4000)]
    debug['radius_candidates'] = radius_candidates
    collected: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    rounds: list[dict[str, object]] = []
    for current_city, current_point in regions:
        for current_radius in radius_candidates:
            for term in query_terms:
                attempt: dict[str, object] = {'term': term, 'current_city': current_city, 'current_point': current_point, 'radius': current_radius}
                try:
                    payload = _client.place_search_nearby_sorted(term, current_point, radius=current_radius, page_size=10, page_index=1) if current_point else _client.place_search_by_region(term, current_city, page_size=10, page_index=1)
                    raw_items = _extract_poi_list(payload, 10)
                    items = [item for item in raw_items if poi_matches_bucket(item, keyword)]
                    attempt['raw_item_count'] = len(raw_items)
                    attempt['item_count'] = len(items)
                except Exception as exc:
                    logger.exception('Nearby search failed')
                    attempt['error'] = exc.__class__.__name__
                    rounds.append(attempt)
                    continue
                for item in items:
                    key = f"{item.get('name', '')}|{item.get('address', '')}|{item.get('location', '')}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    collected.append(item)
                    if len(collected) >= 12:
                        debug.update({'rounds': rounds, 'final_total': len(collected)})
                        return collected, _debug_payload(debug)
                rounds.append(attempt)
    debug.update({'rounds': rounds, 'final_total': len(collected)})
    return collected, _debug_payload(debug)


def search_nearby_bucket(anchor: str, anchor_point: str | None, city: str, keyword: str, fallback_radius: int) -> tuple[list[dict[str, str]], dict[str, object]]:
    primary_items, primary_debug = search_nearby_category(keyword, anchor, anchor_point, city, radius=1500)
    merged = list(primary_items)
    bucket_debug: dict[str, object] = {'primary': primary_debug, 'secondary': [], 'final_count': len(primary_items)}
    secondary_anchor_points: list[str | None] = []
    if anchor_point:
        secondary_anchor_points.append(anchor_point)
    if primary_items:
        secondary_anchor_points.extend(item.get('location') or None for item in primary_items[:3])
    secondary_anchor_points.append(None)
    seen = {f"{item.get('name','')}|{item.get('address','')}|{item.get('location','')}" for item in merged}
    for candidate_point in secondary_anchor_points:
        if len(merged) >= 8:
            break
        extra_items, extra_debug = search_nearby_category(keyword, anchor, candidate_point, city, radius=fallback_radius)
        bucket_debug['secondary'].append(extra_debug)
        for item in extra_items:
            key = f"{item.get('name','')}|{item.get('address','')}|{item.get('location','')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= 8:
                break
    bucket_debug['final_count'] = len(merged)
    return merged[:8], _debug_payload(bucket_debug)


def build_nearby_response(request: ChatRequest) -> dict:
    travel_request = build_travel_request(request)
    forced_anchor = _extract_nearby_anchor_text(request.question)
    city = forced_anchor or resolve_query_city(request)
    anchor, anchor_point, anchor_debug = resolve_nearby_anchor(request.question, city, forced_anchor)
    debug: dict[str, object] = {'city': city, 'anchor': anchor, 'anchor_point': anchor_point, 'anchor_debug': anchor_debug, 'force_current_anchor': bool(request.force_current_anchor), 'forced_anchor': forced_anchor}
    hotel_candidates: list[dict[str, str]] = []
    food_candidates: list[dict[str, str]] = []
    pois: list[dict[str, str]] = []
    try:
        hotel_candidates, debug['hotel_debug'] = search_nearby_bucket(anchor, anchor_point, city, '酒店', 3000)
        food_candidates, debug['food_debug'] = search_nearby_bucket(anchor, anchor_point, city, '餐厅', 2800)
        pois, debug['poi_debug'] = search_nearby_bucket(anchor, anchor_point, city, '景点', 3500)
    except Exception:
        logger.exception('Nearby response build failed')
        debug['search_error'] = 'nearby_search_failed'
    attraction_recommendations = [f"{item['name']}（{item['address']}）" if item.get('address') else item['name'] for item in pois]
    debug.update({'hotel_count': len(hotel_candidates), 'food_count': len(food_candidates), 'poi_count': len(pois)})
    hotel_preview = '；'.join(f"{item.get('name')}（{item.get('address')}）" if item.get('address') else str(item.get('name')) for item in hotel_candidates[:3] if item.get('name'))
    food_preview = '；'.join(f"{item.get('name')}（{item.get('address')}）" if item.get('address') else str(item.get('name')) for item in food_candidates[:3] if item.get('name'))
    poi_preview = '；'.join(attraction_recommendations[:4])
    safe_debug = _debug_payload(debug)
    nearby_data = {
        'city': city,
        'anchor': anchor,
        'anchor_point': anchor_point,
        'anchor_debug': anchor_debug if settings.debug else None,
        'destination_point': anchor_point,
        'attraction_recommendations': attraction_recommendations,
        'transportation_suggestion': [],
        'hotel_candidates': hotel_candidates,
        'food_candidates': food_candidates,
        'debug': safe_debug if settings.debug else None,
    }
    return {
        'conversation_id': request.conversation_id or 'default',
        'answer_type': 'nearby_search',
        'final_answer': '\n'.join([f'酒店：{hotel_preview}' if hotel_preview else '酒店：没有', f'餐厅：{food_preview}' if food_preview else '餐厅：没有', f'景点：{poi_preview}' if poi_preview else '景点：没有']),
        'data': {'nearby': nearby_data},
        'travel_request': travel_request.model_dump(),
        'upload_context': None,
        'meta': {'source': 'poi_search', **({'debug': safe_debug} if settings.debug else {})},
        'error': None,
    }
