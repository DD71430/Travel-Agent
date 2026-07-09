"""Deprecated executor node kept for compatibility with the old workflow."""

from __future__ import annotations

from dataclasses import dataclass

from travel_agent.agent.state import AgentState
from travel_agent.services.travel_planner import build_travel_plan
from travel_agent.tools.search_tool import SearchTool
from travel_agent.tools.tencent_map_tool import TencentMapTool
from travel_agent.tools.tencent_webservice_client import TencentWebServiceClient, TencentWebServiceError


@dataclass(frozen=True)
class RouteReply:
    title: str
    origin: str
    destination: str
    duration: str
    distance: str
    source: str
    confidence: str
    summary: str
    reasons: list[str]
    steps: list[dict[str, str | None]]
    waypoints: str | None
    weather: str | None
    ip_location: str | None
    matrix_hint: str | None


class ExecutorNode:
    def __init__(self) -> None:
        self.map_tool = TencentMapTool()
        self.search_tool = SearchTool()
        self.client = TencentWebServiceClient()

    def _format_reply(self, route_reply: RouteReply, search_count: int) -> str:
        reason_text = '；'.join(route_reply.reasons[:3]) if route_reply.reasons else '综合推荐'
        step_lines = []
        for idx, step in enumerate(route_reply.steps[:5], start=1):
            instruction = step.get('instruction') or '继续前进'
            step_lines.append(f'{idx}. {instruction}')
        steps_text = '\n'.join(step_lines) if step_lines else '1. 暂无可展示步骤'
        waypoint_text = route_reply.waypoints or '无途经点'
        extras = []
        if route_reply.weather:
            extras.append(f'天气：{route_reply.weather}')
        if route_reply.ip_location:
            extras.append(f'位置：{route_reply.ip_location}')
        if route_reply.matrix_hint:
            extras.append(f'矩阵：{route_reply.matrix_hint}')
        extra_text = '；'.join(extras) if extras else '无'
        warning = ''
        if route_reply.source != 'tencent_maps':
            warning = '\n\n数据说明：当前结果来自兜底方案，仅用于演示，不代表真实路况。'
        return (
            f'【推荐路线】{route_reply.title}\n'
            f'出发地：{route_reply.origin}\n'
            f'目的地：{route_reply.destination}\n'
            f'途经点：{waypoint_text}\n'
            f'预计耗时：{route_reply.duration}\n'
            f'预计距离：{route_reply.distance}\n'
            f'数据来源：{route_reply.source}\n'
            f'可信度：{route_reply.confidence}\n'
            f'推荐理由：{reason_text}\n'
            f'补充信息：{extra_text}\n\n'
            f'【路线步骤】\n{steps_text}\n\n'
            f'【补充】\n'
            f'搜索建议数：{search_count}{warning}'
        )

    def _safe_service(self, func, *args, **kwargs) -> dict[str, object]:
        try:
            return func(*args, **kwargs)
        except TencentWebServiceError as exc:
            return {'error': str(exc)}

    def __call__(self, state: AgentState) -> AgentState:
        plan = state.get('plan', [])
        question = state.get('question', '')
        location_entities = state.get('location_entities', {})
        origin = location_entities.get('origin') if isinstance(location_entities, dict) else None
        destination = location_entities.get('destination') if isinstance(location_entities, dict) else None
        if not origin or not destination:
            origin = origin or '起点'
            destination = destination or '终点'
        region = None
        for text in (origin, destination):
            if text and '市' in text:
                region = text[: text.index('市') + 1]
                break

        if state.get('intent') == 'travel_planning':
            travel_request = state.get('route_request')
            if not isinstance(travel_request, dict):
                travel_request = {
                    'origin': origin,
                    'destination': destination,
                    'travel_mode': state.get('travel_mode', 'driving'),
                    'preferences': state.get('preferences'),
                    'conversation_id': state.get('conversation_id'),
                    'waypoints': state.get('waypoints', []),
                    'waypoint_order': state.get('waypoint_order', False),
                }
            from travel_agent.models.travel import TravelPlanRequest
            request = TravelPlanRequest(
                origin=str(travel_request.get('origin') or origin),
                destination=str(travel_request.get('destination') or destination),
                travel_mode=travel_request.get('travel_mode', state.get('travel_mode', 'driving')),
                preferences=travel_request.get('preferences'),
                source_query=question,
                conversation_id=travel_request.get('conversation_id') or state.get('conversation_id'),
                waypoints=[{'name': item.get('name', '')} for item in (travel_request.get('waypoints') or []) if isinstance(item, dict) and item.get('name')],
                waypoint_order=bool(travel_request.get('waypoint_order', False)),
                request_source='chat',
                trip_profile=state.get('trip_profile', {}),
            )
            plan_result = build_travel_plan(request)
            route_reply = plan_result.raw_route.get('best_option', {}) if isinstance(plan_result.raw_route, dict) else {}
            draft_answer = plan_result.summary
            return {
                **state,
                'tool_results': {'travel_plan': plan_result.model_dump()},
                'draft_answer': draft_answer,
                'route_reply': route_reply,
                'route_summary': plan_result.summary,
                'plan': plan,
                'search_summary': {'results': []},
            }

        search_result = self.search_tool.run(query=question, location=state.get('location_hint', ''), region=region)
        ip_loc = self._safe_service(self.client.ip_location, '0.0.0.0')
        weather = self._safe_service(self.client.weather_info, region or origin or destination)
        matrix = self._safe_service(self.client.matrix, state.get('travel_mode', 'driving'), [origin], [destination])
        map_result = self.map_tool.run(
            origin=origin,
            destination=destination,
            travel_mode=state.get('travel_mode', 'driving'),
            conversation_id=state.get('conversation_id'),
            waypoints=state.get('waypoints', []),
            waypoint_order=state.get('waypoint_order', False),
            preferences=state.get('preferences'),
        )
        route_payload = map_result.get('result', {}) if isinstance(map_result.get('result', {}), dict) else {}
        best_option = route_payload.get('raw_route', {}).get('best_option', {}) if isinstance(route_payload, dict) else {}
        route_reply = RouteReply(
            title=map_result.get('route_title', f'{origin} → {destination}'),
            origin=origin,
            destination=destination,
            duration=map_result.get('duration', '未知时长'),
            distance=map_result.get('distance', '未知距离'),
            source=map_result.get('data_source', 'unknown'),
            confidence=map_result.get('confidence', 'unknown'),
            summary=map_result.get('summary', ''),
            reasons=route_payload.get('recommendation_reasons', []) or best_option.get('reasons', []),
            steps=route_payload.get('route_steps', []) or best_option.get('steps', []),
            waypoints='；'.join(w.get('name', '') for w in state.get('waypoints', []) if isinstance(w, dict) and w.get('name')) or None,
            weather=str(weather.get('result', weather.get('message', ''))),
            ip_location=str(ip_loc.get('result', ip_loc.get('message', ''))),
            matrix_hint=str(matrix.get('result', matrix.get('message', ''))),
        )
        draft_answer = self._format_reply(route_reply, len(search_result.get('results', [])))
        return {
            **state,
            'tool_results': {'map': map_result, 'search': search_result, 'weather': weather, 'ip_location': ip_loc, 'matrix': matrix},
            'draft_answer': draft_answer,
            'route_reply': route_reply.__dict__,
            'route_summary': route_reply.summary,
            'plan': plan,
            'search_summary': search_result,
        }
