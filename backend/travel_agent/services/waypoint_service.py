from __future__ import annotations

import re
from typing import Any

from travel_agent.services.location_text_service import strip_stopover_action_suffix

_GENERIC_WORDS = {'景点', '酒店', '餐厅', '博物馆', '公园', '美食', '附近', '沿途', '中途', '路上', '目的地', '顺路'}
_CITY_HINTS = {'北京', '上海', '天津', '重庆', '济南', '成都', '西安', '汉中', '洛阳', '南京', '合肥', '杭州', '郑州', '太原', '泰安', '曲阜', '徐州'}
_ATTRACTION_HINTS = ('山', '寺', '庙', '馆', '宫', '园', '湖', '城墙', '石窟', '遗址', '古城', '古镇', '街', '塔', '三孔')


def _looks_like_list_item(text: str) -> bool:
    cleaned = text.strip(' ，。；;！!?')
    return bool(len(cleaned) >= 2 and cleaned not in _GENERIC_WORDS)


def _split_items(text: str) -> list[str]:
    primary_parts = [item.strip() for item in re.split(r'(?:以及|并且|然后|再|[、,，/])', text) if item.strip()]
    result: list[str] = []
    for part in primary_parts:
        split_part: list[str] | None = None
        for separator in ('和', '及'):
            if separator not in part:
                continue
            pieces = [piece.strip() for piece in part.split(separator) if piece.strip()]
            if len(pieces) == 2 and all(_looks_like_list_item(piece) for piece in pieces):
                split_part = pieces
                break
        result.extend(split_part or [part])
    return result


def _clean_item(item: str) -> str:
    cleaned = item.strip(' ，。；;！!?')
    cleaned = re.sub(r'^(先|再|然后|顺路|中途|沿途|路上|到|去|看|逛|安排|打卡|经过|途经|必须安排|必须去|必须|一定要安排|一定要去|一定要|不要遗漏|不能少|必打卡|必去)+', '', cleaned)
    cleaned = strip_stopover_action_suffix(cleaned)
    cleaned = re.sub(r'(玩|游玩|停留|看看|参观|为主|即可|就行|不要遗漏)$', '', cleaned)
    cleaned = re.sub(r'(三天|两天|一天|四天|五天|六天|七天|\d+天).*$', '', cleaned)
    return cleaned.strip(' ，。；;！!?')


def _is_specific_place(name: str) -> bool:
    return bool(name and len(name) >= 2 and name not in _GENERIC_WORDS)


def _guess_type(name: str) -> str:
    if name.replace('市', '') in _CITY_HINTS or name.endswith(('市', '省', '县', '区')):
        return 'city'
    if any(token in name for token in _ATTRACTION_HINTS):
        return 'attraction'
    return 'unknown'


def _add_detail(result: list[dict[str, Any]], name: str, *, must_visit: bool, source: str = 'parsed') -> None:
    cleaned = _clean_item(name)
    if not _is_specific_place(cleaned):
        return
    existing = next((item for item in result if item['name'] == cleaned), None)
    if existing:
        existing['must_visit'] = bool(existing.get('must_visit') or must_visit)
        return
    result.append(
        {
            'name': cleaned,
            'type': _guess_type(cleaned),
            'must_visit': must_visit,
            'source': source,
            'order': len(result) + 1,
        }
    )


def extract_must_visit_attractions(text: str | None) -> list[str]:
    source = text or ''
    result: list[str] = []
    patterns = (
        r'(?:必须安排|必须去|一定要安排|一定要去|不要遗漏|不能少|必打卡|必去)(?P<items>[^。；;！!]+)',
        r'(?:中途想去|路上想去|沿途想看|中途想看)(?P<items>[^，。；;！!]+)',
        r'(?:到[^，。；;！!]{1,12}后(?:玩\s*\d+\s*天，?)?(?:必须安排|必须去|一定要安排|一定要去|不能少))(?P<items>[^。；;！!]+)',
    )
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            for item in _split_items(match.group('items')):
                cleaned = _clean_item(item)
                if _is_specific_place(cleaned) and cleaned not in result:
                    result.append(cleaned)
    return result


def extract_waypoint_details(text: str | None) -> list[dict[str, Any]]:
    source = text or ''
    result: list[dict[str, Any]] = []
    patterns = (
        (r'(?:途经|经过|路上经过|中途经过|顺路去)(?P<items>[^，。；;！!]+)', False),
        (r'(?:先去)(?P<items>[^，。；;！!]+?)(?:再去|然后去|到|去)(?:[^，。；;！!]*)', False),
        (r'(?:去[^，。；;！!]{1,12}前先去)(?P<items>[^，。；;！!]+)', True),
        (r'(?:必须安排|必须去|一定要安排|一定要去|不要遗漏|不能少|必打卡|必去)(?P<items>[^。；;！!]+)', True),
        (r'(?:中途想去|路上想去|沿途想看|中途想看)(?P<items>[^，。；;！!]+)', True),
        (r'(?:到[^，。；;！!]{1,12}后(?:玩\s*\d+\s*天，?)?(?:必须安排|必须去|一定要安排|一定要去|不能少))(?P<items>[^。；;！!]+)', True),
    )
    for pattern, must_visit in patterns:
        for match in re.finditer(pattern, source):
            for item in _split_items(match.group('items')):
                _add_detail(result, item, must_visit=must_visit)
    must_visits = set(extract_must_visit_attractions(source))
    for item in must_visits:
        _add_detail(result, item, must_visit=True)
    return result


def extract_waypoint_order_mode(text: str | None) -> str:
    source = text or ''
    if any(keyword in source for keyword in ('按我输入的顺序', '不要优化顺序', '按输入顺序')):
        return 'user_order'
    if any(keyword in source for keyword in ('优化途经点顺序', '顺序你来安排', '按顺路程度排序', '帮我优化')):
        return 'optimize'
    return 'unspecified'
