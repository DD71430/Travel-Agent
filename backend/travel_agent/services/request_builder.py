from __future__ import annotations

import json
import re

from travel_agent.models.travel import TravelPlanRequest
from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.intent_service import (
    extract_interest_keywords,
    extract_locations,
    extract_question_waypoints,
    extract_travel_mode,
    extract_trip_details,
    extract_weather_preferences,
)
from travel_agent.services.trip_profile_service import build_trip_profile_from_text
from travel_agent.services.waypoint_service import extract_must_visit_attractions, extract_waypoint_details, extract_waypoint_order_mode


def build_preference_summary(question: str, existing_preferences: str | None, travel_mode: str, trip_details: dict[str, str | None]) -> str:
    parts: list[str] = []
    mode_labels = {'driving': '自驾/驾车', 'walking': '步行', 'transit': '公共交通', 'bicycling': '骑行'}
    parts.append(f'出行方式：{mode_labels.get(travel_mode, travel_mode)}')
    if trip_details.get('budget'):
        parts.append(f'预算：{trip_details["budget"]}元')
    if trip_details.get('duration_days'):
        parts.append(f'行程时长：{trip_details["duration_days"]}天')
    if trip_details.get('nights'):
        parts.append(f'住宿节奏：{trip_details["nights"]}晚')
    interest_keywords = extract_interest_keywords(question)
    if interest_keywords:
        parts.append(f'沿途偏好：{"、".join(interest_keywords)}')
    parts.extend(extract_weather_preferences(question))
    if any(word in question for word in ('老人', '长辈')):
        parts.append('同行人群：有老人，行程节奏宜放缓')
    if any(word in question for word in ('孩子', '亲子', '小朋友')):
        parts.append('同行人群：亲子出行，优先互动性景点')
    if any(word in question for word in ('美食', '小吃', '餐厅')):
        parts.append('游玩偏好：希望加入美食安排')
    if existing_preferences and existing_preferences.strip():
        for item in re.split(r'[；;\n]+', existing_preferences.strip()):
            cleaned = item.strip()
            if cleaned and not cleaned.startswith(('出行方式：', '预算：', '行程时长：', '住宿节奏：')):
                parts.append(cleaned)
    deduped: list[str] = []
    for item in parts:
        if item and item not in deduped:
            deduped.append(item)
    return '；'.join(deduped)


def parse_waypoints(raw: str | None) -> list[dict[str, object]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    waypoints: list[dict[str, object]] = []
    for item in parsed:
        if isinstance(item, dict) and item.get('name'):
            waypoints.append(
                {
                    'name': str(item['name']).strip(),
                    'type': str(item.get('type') or 'unknown'),
                    'must_visit': bool(item.get('must_visit') or False),
                    'source': str(item.get('source') or 'form'),
                }
            )
    return [item for item in waypoints if item['name']]


def build_travel_request(request: ChatRequest) -> TravelPlanRequest:
    parsed_origin, parsed_destination = extract_locations(request.question)
    trip_details = extract_trip_details(request.question)
    travel_mode = extract_travel_mode(request.question, request.travel_mode)
    if request.origin or request.destination:
        origin = (request.origin or parsed_origin or '起点').strip()
        destination = (request.destination or parsed_destination or '终点').strip()
    elif parsed_origin and parsed_destination:
        origin = parsed_origin
        destination = parsed_destination
    else:
        origin = parsed_origin or '起点'
        destination = parsed_destination or '终点'
    source_query = request.question
    if parsed_origin and parsed_destination:
        source_query = f'{parsed_origin}到{parsed_destination} | 天数:{trip_details["duration_days"] or "未知"} | 预算:{trip_details["budget"] or "未知"} | 原始输入:{request.question}'
    preference_text = (request.preferences or '').strip()
    question_text = request.question or ''
    merged_preference_text = '；'.join(part for part in [preference_text, question_text] if part)
    parsed_profile = build_trip_profile_from_text(merged_preference_text, origin=origin, destination=destination, travel_mode=travel_mode)
    waypoint_details = extract_waypoint_details(question_text)
    must_visit_attractions = extract_must_visit_attractions(question_text)
    waypoint_order_mode = extract_waypoint_order_mode(question_text)
    trip_profile = {
        'duration_days': parsed_profile.get('duration_days') or (int(trip_details['duration_days']) if trip_details['duration_days'] else None),
        'nights': parsed_profile.get('nights'),
        'budget': trip_details['budget'],
        'travel_style': '轻松慢游' if any(word in merged_preference_text for word in ('轻松', '慢游', '休闲', '不赶')) else '常规游玩',
        'companions': '家庭/朋友' if any(word in merged_preference_text for word in ('家人', '家庭', '朋友', '亲子')) else '默认',
        'interest_tags': parsed_profile.get('interest_tags', []),
        'avoid_tags': parsed_profile.get('avoid_tags', []),
        'pace': parsed_profile.get('pace', 'normal'),
        'trip_type': parsed_profile.get('trip_type', 'destination_trip'),
        'route_days': parsed_profile.get('route_days'),
        'destination_days': parsed_profile.get('destination_days'),
        'buffer_days': parsed_profile.get('buffer_days'),
        'route_nights': parsed_profile.get('route_nights'),
        'destination_nights': parsed_profile.get('destination_nights'),
        'route_stops': parsed_profile.get('route_stops', []),
        'destination_stay_days': parsed_profile.get('destination_stay_days'),
        'total_days_source': parsed_profile.get('total_days_source'),
        'stage_plan_mode': parsed_profile.get('stage_plan_mode'),
        'explicit_total_days': parsed_profile.get('explicit_total_days'),
        'waypoint_details': waypoint_details,
        'must_visit_attractions': must_visit_attractions,
        'waypoint_order_mode': waypoint_order_mode,
    }
    merged_waypoints: list[dict[str, object]] = []
    for item in [*parse_waypoints(request.waypoints_json), *extract_question_waypoints(question_text), *waypoint_details]:
        name = str(item.get('name', '')).strip()
        if name and not any(existing['name'] == name for existing in merged_waypoints):
            merged_waypoints.append(
                {
                    'name': name,
                    'type': item.get('type') or 'unknown',
                    'must_visit': bool(item.get('must_visit') or name in must_visit_attractions),
                    'source': item.get('source') or 'parsed',
                }
            )
    for name in must_visit_attractions:
        if not any(existing['name'] == name for existing in merged_waypoints):
            merged_waypoints.append({'name': name, 'type': 'attraction', 'must_visit': True, 'source': 'parsed'})
    waypoint_order = bool(request.waypoint_order) if request.waypoint_order is not None else False
    if waypoint_order_mode == 'user_order':
        waypoint_order = False
    elif waypoint_order_mode == 'optimize':
        waypoint_order = True
    return TravelPlanRequest(
        origin=origin,
        destination=destination,
        travel_mode=travel_mode,  # type: ignore[arg-type]
        preferences=build_preference_summary(question_text, preference_text, travel_mode, trip_details),
        source_query=source_query,
        conversation_id=request.conversation_id,
        waypoints=merged_waypoints,
        waypoint_order=waypoint_order,
        request_source='chat',
        trip_profile=trip_profile,
    )
