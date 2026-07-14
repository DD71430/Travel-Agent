from __future__ import annotations

import math
from typing import Any

INTERCITY_MODE_LABELS = {
    'driving': '自驾/驾车',
    'high_speed_rail': '高铁/动车',
    'train': '火车/铁路',
    'flight': '飞机/航班',
    'coach': '长途大巴',
    'transit': '公共交通',
    'unknown': '未指定',
}

LOCAL_MODE_LABELS = {
    'driving': '自驾/打车',
    'taxi': '打车/网约车',
    'transit': '市内公共交通',
    'walking': '步行',
    'bicycling': '骑行',
    'mixed': '市内公共交通/打车',
    'unknown': '未指定',
}

_INTERCITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('high_speed_rail', ('高铁', '动车', '城际铁路', '城际列车')),
    ('flight', ('飞机', '航班', '机场', '坐飞机', '乘飞机')),
    ('train', ('火车', '列车', '铁路', '普速', '绿皮')),
    ('coach', ('长途汽车', '大巴', '客车', '巴士')),
    ('driving', ('自驾', '驾车', '开车', '租车')),
)

_LOCAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('taxi', ('打车', '出租车', '网约车')),
    ('transit', ('地铁', '公交', '公共交通', '换乘')),
    ('walking', ('步行', '走路', '徒步')),
    ('bicycling', ('骑行', '单车', '自行车')),
    ('driving', ('自驾', '驾车', '开车', '租车')),
)

_ROUTE_MODE_BY_INTERCITY = {
    'high_speed_rail': 'transit',
    'train': 'transit',
    'flight': 'transit',
    'coach': 'transit',
    'transit': 'transit',
    'driving': 'driving',
}

_SPEED_KMH = {
    'high_speed_rail': 220,
    'train': 120,
    'flight': 720,
    'coach': 75,
    'transit': 70,
}

_TRANSFER_BUFFER_MINUTES = {
    'high_speed_rail': 90,
    'train': 75,
    'flight': 150,
    'coach': 45,
    'transit': 45,
}


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def parse_transport_modes(text: str | None, fallback_travel_mode: str | None = None) -> dict[str, str]:
    source = text or ''
    intercity_mode = 'unknown'
    for mode, keywords in _INTERCITY_KEYWORDS:
        if _contains_any(source, keywords):
            intercity_mode = mode
            break

    local_mode = 'unknown'
    for mode, keywords in _LOCAL_KEYWORDS:
        if _contains_any(source, keywords):
            local_mode = mode
            break

    fallback_mode = fallback_travel_mode or 'driving'
    if intercity_mode == 'unknown':
        intercity_mode = fallback_mode if fallback_mode in {'driving', 'transit', 'walking', 'bicycling'} else 'unknown'
    if local_mode == 'unknown':
        if intercity_mode in {'high_speed_rail', 'train', 'flight', 'coach'}:
            local_mode = 'mixed'
        elif fallback_mode in {'driving', 'transit', 'walking', 'bicycling'}:
            local_mode = fallback_mode
        else:
            local_mode = 'mixed'

    route_mode = _ROUTE_MODE_BY_INTERCITY.get(intercity_mode, fallback_mode if fallback_mode in {'driving', 'walking', 'transit', 'bicycling'} else 'driving')
    if local_mode in {'transit', 'walking', 'bicycling', 'driving'} and intercity_mode == 'unknown':
        route_mode = local_mode

    return {
        'intercity_mode': intercity_mode,
        'intercity_label': INTERCITY_MODE_LABELS.get(intercity_mode, intercity_mode),
        'local_mode': local_mode,
        'local_label': LOCAL_MODE_LABELS.get(local_mode, local_mode),
        'travel_mode': route_mode,
        'transport_preference_source': 'question' if source.strip() else 'default',
    }


def transport_mode_label(mode: str | None, *, local: bool = False) -> str:
    labels = LOCAL_MODE_LABELS if local else INTERCITY_MODE_LABELS
    return labels.get(mode or 'unknown', mode or '未指定')


def estimate_intercity_transport_block(
    *,
    origin: str,
    destination: str,
    mode: str,
    distance_meters: int = 0,
    fallback_minutes: int = 0,
) -> dict[str, Any]:
    normalized_mode = mode if mode in INTERCITY_MODE_LABELS else 'driving'
    if normalized_mode == 'driving':
        total_minutes = max(0, fallback_minutes)
        return {
            'mode': 'driving',
            'label': INTERCITY_MODE_LABELS['driving'],
            'origin': origin,
            'destination': destination,
            'ride_minutes': total_minutes,
            'buffer_minutes': 0,
            'total_minutes': total_minutes,
            'summary': f'自驾约{total_minutes}分钟' if total_minutes else '自驾时间待确认',
        }

    km = max(0.0, distance_meters / 1000)
    speed = _SPEED_KMH.get(normalized_mode, 70)
    ride_minutes = max(45, int(math.ceil(km / speed * 60))) if km else max(45, fallback_minutes)
    buffer_minutes = _TRANSFER_BUFFER_MINUTES.get(normalized_mode, 60)
    total_minutes = ride_minutes + buffer_minutes
    label = INTERCITY_MODE_LABELS.get(normalized_mode, normalized_mode)
    buffer_text = '进站候车、出站接驳'
    if normalized_mode == 'flight':
        buffer_text = '值机安检、机场往返接驳'
    elif normalized_mode == 'coach':
        buffer_text = '进站候车、到站接驳'
    return {
        'mode': normalized_mode,
        'label': label,
        'origin': origin,
        'destination': destination,
        'ride_minutes': ride_minutes,
        'buffer_minutes': buffer_minutes,
        'total_minutes': total_minutes,
        'summary': f'{label}约{ride_minutes}分钟，含{buffer_text}约{total_minutes}分钟',
    }
