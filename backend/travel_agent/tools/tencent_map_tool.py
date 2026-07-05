from __future__ import annotations

from typing import Any

from travel_agent.models.travel import TravelPlanRequest
from travel_agent.services.travel_planner import build_travel_plan
from travel_agent.tools.base import BaseTool


class TencentMapTool(BaseTool):
    name = 'tencent_map'

    def run(self, **kwargs: Any) -> dict[str, Any]:
        waypoints_raw = kwargs.get('waypoints') or []
        waypoints = []
        for item in waypoints_raw:
            if isinstance(item, dict) and item.get('name'):
                waypoints.append({'name': str(item['name'])})
        request = TravelPlanRequest(
            origin=str(kwargs.get('origin', '起点')),
            destination=str(kwargs.get('destination', '终点')),
            travel_mode=str(kwargs.get('travel_mode', 'driving')),
            preferences=kwargs.get('preferences'),
            conversation_id=kwargs.get('conversation_id'),
            waypoints=waypoints,
            waypoint_order=bool(kwargs.get('waypoint_order', False)),
        )
        result = build_travel_plan(request)
        return {
            'provider': result.raw_route.get('provider', 'tencent_maps'),
            'data_source': result.data_source,
            'confidence': result.confidence,
            'route_title': result.route_title,
            'distance': result.raw_route.get('best_option', {}).get('distance', ''),
            'duration': result.raw_route.get('best_option', {}).get('duration', ''),
            'summary': result.summary,
            'result': result.model_dump(),
            'route_error': result.route_error,
        }
