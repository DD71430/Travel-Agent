from __future__ import annotations

from typing import Any


_ROUTE_STOP_HINTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (('济南', '成都'), ('郑州', '洛阳', '西安', '汉中')),
    (('成都', '济南'), ('汉中', '西安', '洛阳', '郑州')),
    (('北京', '西安'), ('石家庄', '太原', '平遥', '临汾')),
    (('西安', '北京'), ('临汾', '平遥', '太原', '石家庄')),
    (('杭州', '南京'), ('湖州', '宜兴', '溧阳')),
    (('南京', '杭州'), ('溧阳', '宜兴', '湖州')),
    (('济南', '南京'), ('泰安', '曲阜', '徐州')),
    (('南京', '济南'), ('徐州', '曲阜', '泰安')),
)


def _clean_city(value: str | None) -> str:
    return (value or '').replace('市', '').strip()


def _spread_stops(candidates: tuple[str, ...], route_days: int) -> list[str]:
    if route_days <= 0:
        return []
    if len(candidates) <= route_days:
        return list(candidates)
    if route_days == 1:
        return [candidates[len(candidates) // 2]]
    step = (len(candidates) - 1) / max(1, route_days - 1)
    selected: list[str] = []
    for index in range(route_days):
        name = candidates[round(index * step)]
        if name not in selected:
            selected.append(name)
    return selected[:route_days]


def _match_fallback_route(origin: str, destination: str) -> tuple[str, ...]:
    origin_clean = _clean_city(origin)
    destination_clean = _clean_city(destination)
    for (start, end), stops in _ROUTE_STOP_HINTS:
        if _clean_city(start) in origin_clean and _clean_city(end) in destination_clean:
            return stops
    return ()


def infer_route_stops(
    origin: str,
    destination: str,
    route_days: int,
    waypoints: list[dict[str, Any]] | None = None,
    route_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if route_days <= 0:
        return []
    explicit_waypoints = [item for item in (waypoints or []) if str(item.get('name') or '').strip()]
    if explicit_waypoints:
        stops: list[dict[str, Any]] = []
        for index, waypoint in enumerate(explicit_waypoints, start=1):
            name = str(waypoint.get('name') or '').strip()
            stage_day = waypoint.get('preferred_day') or min(route_days, max(1, round((index - 1) / max(1, len(explicit_waypoints) - 1) * max(0, route_days - 1)) + 1))
            waypoint_type = str(waypoint.get('type') or 'unknown')
            must_visit = bool(waypoint.get('must_visit') or False)
            stops.append(
                {
                    'name': name,
                    'type': waypoint_type if waypoint_type in {'city', 'attraction', 'poi', 'unknown'} else 'unknown',
                    'stage_day': int(stage_day),
                    'stay_days': waypoint.get('stay_days', 0),
                    'stay_nights': waypoint.get('stay_nights', 0),
                    'preferred_day': waypoint.get('preferred_day') or stage_day,
                    'must_visit': must_visit,
                    'reason': waypoint.get('reason') or ('用户明确要求沿途安排' if must_visit else f'用户明确指定途经{name}，优先作为沿途第{stage_day}天停留点。'),
                    'data_source': waypoint.get('source') or 'user_waypoint',
                }
            )
        if len(stops) > route_days * 3:
            for item in stops:
                item['warning'] = '途经点较多，已压缩为重点停留，其余作为备选。'
        return stops

    context_stops = route_context.get('route_stops') if isinstance(route_context, dict) else None
    if isinstance(context_stops, list) and context_stops:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(context_stops[:route_days], start=1):
            if isinstance(item, dict) and item.get('name'):
                normalized.append({**item, 'stage_day': item.get('stage_day') or index})
        if normalized:
            return normalized

    fallback = _spread_stops(_match_fallback_route(origin, destination), route_days)
    if not fallback:
        fallback = [_clean_city(destination) or destination]
    return [
        {
            'name': name,
            'type': 'inferred_city' if name != destination else 'destination_fallback',
            'stage_day': index,
            'reason': f'{name}适合作为{_clean_city(origin)}到{_clean_city(destination)}方向第{index}天的沿途停留点。',
            'data_source': 'fallback_city_hint' if name != destination else 'destination_fallback',
        }
        for index, name in enumerate(fallback[:route_days], start=1)
    ]
