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


_CITY_FALLBACK_POIS: dict[str, tuple[tuple[str, str], ...]] = {
    '成都': (('成都博物馆', '博物馆'), ('金沙遗址博物馆', '历史文化'), ('人民公园', '公园'), ('宽窄巷子', '历史文化街区'), ('锦里古街', '美食街')),
    '西安': (('陕西历史博物馆', '博物馆'), ('西安城墙', '历史文化'), ('大雁塔', '历史文化'), ('大唐芙蓉园', '公园'), ('回民街', '美食街')),
    '南京': (('南京博物院', '博物馆'), ('玄武湖公园', '公园'), ('夫子庙秦淮风光带', '历史文化'), ('中山陵', '历史文化')),
    '郑州': (('河南博物院', '博物馆'), ('郑州黄河文化公园', '公园'), ('二七纪念塔', '历史文化')),
    '洛阳': (('洛阳博物馆', '博物馆'), ('龙门石窟', '历史文化'), ('隋唐洛阳城遗址公园', '公园')),
    '汉中': (('汉中博物馆', '博物馆'), ('兴汉胜境', '历史文化'), ('汉江湿地公园', '公园')),
}


def _clean_city(value: str | None) -> str:
    return (value or '').replace('市', '').strip()


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
        candidates.append(
            {
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
        )
    return candidates


def fetch_route_poi_candidates(route_stops: list[dict[str, Any]], trip_profile: dict[str, Any], route_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for stop in route_stops:
        city = str(stop.get('name') or '').strip()
        if not city:
            continue
        if stop.get('must_visit') or stop.get('type') in {'attraction', 'poi'}:
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
                    'must_visit': bool(stop.get('must_visit') or True),
                    'source': 'user_required' if stop.get('must_visit') else 'user_waypoint',
                    'data_source': 'user_required' if stop.get('must_visit') else 'user_waypoint',
                    'reason_hint': stop.get('reason') or '用户明确要求安排',
                    'stop_name': city,
                }
            )
        for poi in _fallback_pois_for_city(city, trip_profile, stage='route', stage_day=int(stop.get('stage_day') or 1)):
            poi['stop_name'] = city
            poi['reason_hint'] = stop.get('reason')
            candidates.append(poi)
    must_visits = [str(item) for item in trip_profile.get('must_visit_attractions') or [] if str(item).strip()]
    destination = str(trip_profile.get('destination') or '')
    for name in must_visits:
        if destination and destination in name:
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
    candidates = _fallback_pois_for_city(destination, trip_profile, stage='destination')
    for name in [str(item) for item in trip_profile.get('must_visit_attractions') or [] if str(item).strip()]:
        if destination in name or _clean_city(destination) in name or name.startswith(_clean_city(destination)):
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
