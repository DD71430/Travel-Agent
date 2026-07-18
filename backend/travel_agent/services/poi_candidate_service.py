from __future__ import annotations

from typing import Any


_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    '博物馆': ('博物馆', '纪念馆', '美术馆'),
    '公园': ('公园', '湿地公园', '湖公园'),
    '历史文化': ('历史文化街区', '古城', '遗址'),
    '古城': ('古城', '古镇', '老街'),
    '美食': ('小吃街', '老字号', '夜市'),
    '亲子': ('科技馆', '动物园', '乐园'),
    '自然风光': ('湿地', '湖泊', '森林公园'),
}

_ATTRACTION_ALLOW_KEYWORDS = (
    '景区',
    '风景名胜',
    '博物馆',
    '美术馆',
    '纪念馆',
    '科技馆',
    '展览馆',
    '非遗馆',
    '公园',
    '湿地',
    '湖',
    '山',
    '古城',
    '古镇',
    '历史文化街区',
    '遗址',
    '寺',
    '塔',
    '园林',
    '动物园',
    '植物园',
    '海洋馆',
    '乐园',
    '观景台',
    '城墙',
)
_NON_ATTRACTION_BLOCK_KEYWORDS = (
    '星巴克',
    '咖啡',
    '奶茶',
    '餐厅',
    '饭店',
    '火锅',
    '烧烤',
    '小吃',
    '酒店',
    '宾馆',
    '民宿',
    '停车场',
    '公司',
    '写字楼',
    '购物中心',
    '商场',
    '超市',
    '便利店',
    '银行',
    '药店',
    '小区',
    '住宅',
    '门店',
    '营业厅',
)
_FOOD_KEYWORDS = ('餐厅', '饭店', '火锅', '烧烤', '小吃', '咖啡', '奶茶', '地方菜', '老字号', '美食')
_HOTEL_KEYWORDS = ('酒店', '宾馆', '民宿', '客栈', '住宿')
_CITY_HINTS = ('北京', '上海', '广州', '深圳', '杭州', '济南', '南京', '徐州', '成都', '西安', '郑州', '洛阳', '汉中', '泰安', '曲阜', '苏州', '无锡', '湖州')
_HANGZHOU_FAR_SUBURBS = ('建德', '淳安', '桐庐', '临安', '富阳')


_CITY_FALLBACK_POIS: dict[str, tuple[tuple[str, str], ...]] = {
    '杭州': (('西湖风景名胜区', '风景名胜区'), ('灵隐寺', '寺庙'), ('杭州博物馆', '博物馆'), ('小河直街历史文化街区', '历史文化街区'), ('京杭大运河杭州景区', '景区')),
    '徐州': (('徐州博物馆', '博物馆'), ('云龙湖风景区', '风景名胜区'), ('户部山历史文化街区', '历史文化街区'), ('戏马台', '历史遗址')),
    '成都': (('成都博物馆', '博物馆'), ('金沙遗址博物馆', '历史文化'), ('人民公园', '公园'), ('宽窄巷子', '历史文化街区'), ('锦里古街', '美食街')),
    '西安': (('陕西历史博物馆', '博物馆'), ('西安城墙', '历史文化'), ('大雁塔', '历史文化'), ('大唐芙蓉园', '公园'), ('回民街', '美食街')),
    '南京': (('南京博物院', '博物馆'), ('玄武湖公园', '公园'), ('夫子庙秦淮风光带', '历史文化'), ('中山陵', '历史文化')),
    '郑州': (('河南博物院', '博物馆'), ('郑州黄河文化公园', '公园'), ('二七纪念塔', '历史文化')),
    '洛阳': (('洛阳博物馆', '博物馆'), ('龙门石窟', '历史文化'), ('隋唐洛阳城遗址公园', '公园')),
    '汉中': (('汉中博物馆', '博物馆'), ('兴汉胜境', '历史文化'), ('汉江湿地公园', '公园')),
}


def _clean_city(value: str | None) -> str:
    return (value or '').replace('市', '').strip()


def _route_stop_name_set(trip_profile: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in trip_profile.get('route_stops') or []:
        if not isinstance(item, dict):
            continue
        name = _clean_city(str(item.get('name') or ''))
        if name:
            names.add(name)
    return names


def _combined_poi_text(poi: dict[str, Any]) -> str:
    return ' '.join(str(poi.get(key) or '') for key in ('name', 'title', 'category', 'type', 'address'))


def is_food_poi(poi: dict[str, Any]) -> bool:
    return any(keyword in _combined_poi_text(poi) for keyword in _FOOD_KEYWORDS)


def is_hotel_poi(poi: dict[str, Any]) -> bool:
    return any(keyword in _combined_poi_text(poi) for keyword in _HOTEL_KEYWORDS)


def is_valid_attraction_poi(poi: dict[str, Any]) -> bool:
    combined = _combined_poi_text(poi)
    if not combined.strip():
        return False
    if any(keyword in combined for keyword in _NON_ATTRACTION_BLOCK_KEYWORDS):
        return False
    if bool(poi.get('must_visit')) or str(poi.get('must_visit')).lower() == 'true':
        return True
    return any(keyword in combined for keyword in _ATTRACTION_ALLOW_KEYWORDS)


def _explicitly_mentions_poi_area(poi: dict[str, Any], profile: dict[str, Any]) -> bool:
    combined = _combined_poi_text(poi)
    source = str(profile.get('source_text') or profile.get('preferences') or '')
    must_visits = ' '.join(str(item) for item in profile.get('must_visit_attractions') or [])
    route_stops = ' '.join(str(item.get('name') or '') for item in profile.get('route_stops') or [] if isinstance(item, dict))
    return bool(combined and any(part and part in f'{source} {must_visits} {route_stops}' for part in re_split_place_tokens(combined)))


def re_split_place_tokens(text: str) -> list[str]:
    return [item for item in re_split_clean(text) if len(item) >= 2]


def re_split_clean(text: str) -> list[str]:
    import re

    return [item.strip() for item in re.split(r'[\s()（）;；,，、]+', text) if item.strip()]


def is_poi_in_planning_scope(poi: dict[str, Any], anchor_city: str, route_context: dict[str, Any], profile: dict[str, Any]) -> bool:
    anchor = _clean_city(anchor_city)
    combined = _combined_poi_text(poi)
    if not anchor:
        return True
    mentioned_cities = [city for city in _CITY_HINTS if city in combined]
    if mentioned_cities and anchor not in mentioned_cities:
        return False
    if anchor == '杭州' and any(suburb in combined for suburb in _HANGZHOU_FAR_SUBURBS):
        source = str(profile.get('source_text') or profile.get('preferences') or '')
        must_visits = [str(item) for item in profile.get('must_visit_attractions') or []]
        route_stops = [str(item.get('name') or '') for item in profile.get('route_stops') or [] if isinstance(item, dict)]
        explicitly_requested = any(suburb in source for suburb in _HANGZHOU_FAR_SUBURBS)
        explicitly_requested = explicitly_requested or any(any(suburb in item for suburb in _HANGZHOU_FAR_SUBURBS) for item in must_visits + route_stops)
        is_route_stage = str(route_context.get('stage') or '') == 'route'
        is_surrounding_day = any(keyword in source for keyword in ('杭州周边', '远郊一日游', '建德', '淳安', '桐庐', '临安', '富阳'))
        if not (explicitly_requested or is_route_stage and bool(poi.get('route_order')) or is_surrounding_day):
            return False
    return True


def _interest_keywords(trip_profile: dict[str, Any]) -> list[str]:
    tags = [str(item) for item in trip_profile.get('interest_tags') or []]
    keywords: list[str] = []
    for tag in tags:
        keywords.extend(_TAG_KEYWORDS.get(tag, (tag,)))
    return keywords or ['博物馆', '公园', '历史文化街区']


def _fallback_pois_for_city(city: str, trip_profile: dict[str, Any], *, stage: str, stage_day: int | None = None) -> list[dict[str, Any]]:
    city_clean = _clean_city(city)
    base = list(_CITY_FALLBACK_POIS.get(city_clean, ()))
    for keyword in _interest_keywords(trip_profile):
        name = f'{city_clean}{keyword}'
        category = keyword
        if not any(existing_name == name for existing_name, _ in base):
            base.append((name, category))
    candidates: list[dict[str, Any]] = []
    for index, (name, category) in enumerate(base[:8], start=1):
        poi = {
            'name': name,
            'address': f'{city_clean}核心游览区',
            'category': category,
            'location': '',
            'stage': stage,
            'stage_day': stage_day,
            'route_order': index if stage == 'route' else None,
            'estimated_minutes': 90 if stage == 'route' else 150,
            'data_source': 'fallback',
        }
        if is_valid_attraction_poi(poi) and is_poi_in_planning_scope(poi, city_clean, {'stage': stage}, trip_profile):
            candidates.append(poi)
    return candidates


def fetch_route_poi_candidates(route_stops: list[dict[str, Any]], trip_profile: dict[str, Any], route_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for stop in route_stops:
        city = str(stop.get('name') or '').strip()
        if not city:
            continue
        stop_type = stop.get('type')
        is_must_visit = bool(stop.get('must_visit'))
        if is_must_visit or stop_type in {'city', 'attraction', 'poi'}:
            candidates.append(
                {
                    'name': city,
                    'address': '用户指定沿途停留点',
                    'category': '用户指定途经点',
                    'location': '',
                    'stage': 'route',
                    'stage_day': int(stop.get('stage_day') or 1),
                    'route_order': int(stop.get('stage_day') or 1),
                    'estimated_minutes': 120,
                    'must_visit': is_must_visit,
                    'source': 'user_required' if is_must_visit else 'user_waypoint',
                    'data_source': 'user_required' if is_must_visit else 'user_waypoint',
                    'reason_hint': stop.get('reason') or '用户明确要求安排',
                    'stop_name': city,
                }
            )
        for poi in _fallback_pois_for_city(city, trip_profile, stage='route', stage_day=int(stop.get('stage_day') or 1)):
            poi['stop_name'] = city
            poi['reason_hint'] = stop.get('reason')
            candidates.append(poi)
    must_visits = [str(item) for item in trip_profile.get('must_visit_attractions') or [] if str(item).strip()]
    route_stop_names = _route_stop_name_set(trip_profile)
    for name in must_visits:
        if _clean_city(name) not in route_stop_names:
            continue
        candidates.insert(
            0,
            {
                'name': name,
                'address': '用户指定沿途必去景点',
                'category': '用户指定必去',
                'location': '',
                'stage': 'route',
                'stage_day': 1,
                'route_order': 0,
                'estimated_minutes': 120,
                'must_visit': True,
                'source': 'user_required',
                'data_source': 'user_required',
                'reason_hint': '用户明确要求安排',
            },
        )
    return _dedupe_candidates(candidates)


def fetch_destination_poi_candidates(destination: str, trip_profile: dict[str, Any], route_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    candidates = [
        poi
        for poi in _fallback_pois_for_city(destination, trip_profile, stage='destination')
        if is_valid_attraction_poi(poi) and is_poi_in_planning_scope(poi, destination, {**(route_context or {}), 'stage': 'destination'}, trip_profile)
    ]
    route_stop_names = _route_stop_name_set(trip_profile)
    for name in [str(item) for item in trip_profile.get('must_visit_attractions') or [] if str(item).strip()]:
        clean_name = _clean_city(name)
        if clean_name in route_stop_names:
            continue
        candidates.insert(
            0,
            {
                'name': name,
                'address': '用户指定目的地必去景点',
                'category': '用户指定必去',
                'location': '',
                'stage': 'destination',
                'stage_day': None,
                'route_order': None,
                'estimated_minutes': 150,
                'must_visit': True,
                'source': 'user_required',
                'data_source': 'user_required',
                'reason_hint': '用户明确要求安排',
            },
        )
    return _dedupe_candidates(candidates)


def fetch_meal_candidates(anchor_points: list[dict[str, Any]], trip_profile: dict[str, Any]) -> list[dict[str, str]]:
    anchors = [str(item.get('name') or '').strip() for item in anchor_points if str(item.get('name') or '').strip()]
    city = anchors[-1] if anchors else '目的地'
    return [
        {'name': f'{city}本地特色餐厅', 'address': f'{city}当天收尾景点附近', 'category': '地方菜', 'location': ''},
        {'name': f'{city}老字号小吃', 'address': f'{city}住宿点步行范围', 'category': '小吃', 'location': ''},
    ]


def fetch_hotel_candidates(anchor_points: list[dict[str, Any]], trip_profile: dict[str, Any]) -> list[dict[str, str]]:
    anchors = [str(item.get('name') or '').strip() for item in anchor_points if str(item.get('name') or '').strip()]
    city = anchors[-1] if anchors else '目的地'
    return [
        {'name': f'{city}景点附近酒店', 'address': f'{city}当天最后一个景点附近', 'category': '酒店', 'location': ''},
        {'name': f'{city}交通换乘酒店', 'address': f'{city}主城区交通便利商圈', 'category': '酒店', 'location': ''},
    ]


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        key = f"{item.get('name', '')}|{item.get('address', '')}"
        if not item.get('name') or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
