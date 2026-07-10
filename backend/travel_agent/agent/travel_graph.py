from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from travel_agent.core.config import get_settings
from travel_agent.models.travel import TravelPlanRequest
from travel_agent.schemas.chat import ChatRequest
from travel_agent.services.intent_service import classify_chat_intent
from travel_agent.services.llm_chat_service import build_general_response, generate_general_answer
from travel_agent.services.nearby_service import build_nearby_response
from travel_agent.services.request_builder import build_travel_request
from travel_agent.services.travel_planner import build_travel_plan
from travel_agent.services.trip_profile_service import build_trip_profile, decide_trip_type

settings = get_settings()


class UnifiedAgentState(TypedDict, total=False):
    request: ChatRequest
    travel_request: TravelPlanRequest
    intent: str
    answer_type: str
    final_answer: str
    data: dict[str, Any]
    meta: dict[str, Any]
    error: str | None
    upload_context: dict[str, Any] | None
    conversation_id: str
    response: dict[str, Any]
    processing_notes: list[str]
    iteration: int
    retry_reason: str
    route_summary: str
    trip_profile: dict[str, Any]
    route_context: dict[str, Any]


def _meta_with_notes(meta: dict[str, Any] | None, notes: list[str]) -> dict[str, Any]:
    result = dict(meta or {})
    if settings.debug or settings.return_debug_meta:
        result['notes'] = notes
    else:
        result.pop('debug', None)
        result.pop('notes', None)
    return result


def _ensure_request(state: UnifiedAgentState) -> UnifiedAgentState:
    request = state['request']
    conversation_id = request.conversation_id or state.get('conversation_id') or 'default'
    if request.conversation_id != conversation_id:
        request = ChatRequest(**{**request.model_dump(), 'conversation_id': conversation_id})
    return {**state, 'request': request, 'conversation_id': conversation_id, 'iteration': int(state.get('iteration', 0) or 0), 'processing_notes': state.get('processing_notes', []) or []}


def _classify(state: UnifiedAgentState) -> UnifiedAgentState:
    intent = classify_chat_intent(state['request'].question)
    notes = [*state.get('processing_notes', []), f'intent={intent}']
    return {**state, 'intent': intent, 'processing_notes': notes}


def _prepare_travel_request(state: UnifiedAgentState) -> UnifiedAgentState:
    travel_request = build_travel_request(state['request'])
    notes = [*state.get('processing_notes', []), 'travel_request_built']
    return {**state, 'travel_request': travel_request, 'processing_notes': notes}


def _extract_trip_profile_node(state: UnifiedAgentState) -> UnifiedAgentState:
    profile = build_trip_profile(state['travel_request'])
    notes = [*state.get('processing_notes', []), f'trip_profile={profile.get("pace", "normal")}']
    return {**state, 'trip_profile': profile, 'processing_notes': notes}


def _build_route_context_node(state: UnifiedAgentState) -> UnifiedAgentState:
    profile = state.get('trip_profile', {})
    route_context = {
        'travel_mode': state['travel_request'].travel_mode,
        'duration_days': profile.get('duration_days'),
        'stage': 'route_context_deferred_to_travel_planner',
    }
    notes = [*state.get('processing_notes', []), 'route_context_prepared']
    return {**state, 'route_context': route_context, 'processing_notes': notes}


def _decide_trip_type_node(state: UnifiedAgentState) -> UnifiedAgentState:
    profile = dict(state.get('trip_profile', {}))
    request = state['travel_request']
    profile['trip_type'] = decide_trip_type({**profile, 'origin': request.origin, 'destination': request.destination, 'travel_mode': request.travel_mode, 'source_text': request.source_query or request.preferences or ''}, state.get('route_context'))
    notes = [*state.get('processing_notes', []), f'trip_type={profile["trip_type"]}']
    return {**state, 'trip_profile': profile, 'processing_notes': notes}


def _fetch_route_options_node(state: UnifiedAgentState) -> UnifiedAgentState:
    notes = [*state.get('processing_notes', []), 'route_options_fetch_deferred']
    return {**state, 'processing_notes': notes}


def _fetch_poi_candidates_node(state: UnifiedAgentState) -> UnifiedAgentState:
    notes = [*state.get('processing_notes', []), 'poi_candidates_fetch_deferred']
    return {**state, 'processing_notes': notes}


def _rank_poi_candidates_node(state: UnifiedAgentState) -> UnifiedAgentState:
    notes = [*state.get('processing_notes', []), 'poi_ranking_deferred']
    return {**state, 'processing_notes': notes}


def _build_daily_itinerary_node(state: UnifiedAgentState) -> UnifiedAgentState:
    notes = [*state.get('processing_notes', []), 'daily_itinerary_deferred']
    return {**state, 'processing_notes': notes}


async def _finalize_travel_response(state: UnifiedAgentState) -> UnifiedAgentState:
    travel_request = state['travel_request']
    if state.get('trip_profile'):
        travel_request = TravelPlanRequest(**{**travel_request.model_dump(), 'trip_profile': {**travel_request.trip_profile, **state['trip_profile']}})
    travel_plan = await asyncio.to_thread(build_travel_plan, travel_request)
    notes = state.get('processing_notes', [])
    response = {
        'conversation_id': travel_plan.conversation_id,
        'answer_type': 'travel_planning',
        'final_answer': travel_plan.summary,
        'data': {'travel_plan': travel_plan.model_dump()},
        'travel_request': travel_request.model_dump(),
        'upload_context': state.get('upload_context'),
        'meta': _meta_with_notes({'source': travel_plan.data_source}, notes),
        'error': travel_plan.route_error,
    }
    return {**state, 'conversation_id': travel_plan.conversation_id, 'answer_type': 'travel_planning', 'final_answer': travel_plan.summary, 'route_summary': travel_plan.summary, 'data': response['data'], 'meta': response['meta'], 'error': response['error'], 'response': response}


async def _build_nearby(state: UnifiedAgentState) -> UnifiedAgentState:
    response = await asyncio.to_thread(build_nearby_response, state['request'])
    response['upload_context'] = state.get('upload_context')
    response['meta'] = _meta_with_notes(response.get('meta'), state.get('processing_notes', []))
    return {**state, 'answer_type': response['answer_type'], 'final_answer': response['final_answer'], 'data': response['data'], 'meta': response['meta'], 'error': response['error'], 'response': response}


async def _build_general(state: UnifiedAgentState) -> UnifiedAgentState:
    response = build_general_response(state['request'])
    response['upload_context'] = state.get('upload_context')
    response['final_answer'] = await generate_general_answer(state['request'].question, state['conversation_id'], state.get('memory_store'))  # type: ignore[arg-type]
    response['meta'] = _meta_with_notes(response.get('meta'), state.get('processing_notes', []))
    return {**state, 'answer_type': response['answer_type'], 'final_answer': response['final_answer'], 'data': response['data'], 'meta': response['meta'], 'error': response['error'], 'response': response}


def _after_classify(state: UnifiedAgentState) -> str:
    return state.get('intent', 'general_chat')


def _after_travel_reflect(state: UnifiedAgentState) -> str:
    if not state.get('final_answer'):
        return 'repair_travel'
    return 'end'


def _repair_travel(state: UnifiedAgentState) -> UnifiedAgentState:
    notes = [*state.get('processing_notes', []), f'repair:{state.get("retry_reason") or state.get("error") or "empty_response"}']
    response = state.get('response') or {}
    response['meta'] = _meta_with_notes(response.get('meta'), notes)
    response['final_answer'] = response.get('final_answer') or state.get('route_summary') or '暂时没有生成可用结果，请稍后重试。'
    return {**state, 'processing_notes': notes, 'response': response, 'final_answer': response['final_answer']}


class _AsyncGraphRunner:
    def __init__(self, graph):
        self.graph = graph

    async def ainvoke(self, state: UnifiedAgentState) -> UnifiedAgentState:
        return await self.graph.ainvoke(state)

    def invoke(self, state: UnifiedAgentState) -> UnifiedAgentState:
        return self.graph.invoke(state)


def build_unified_graph():
    graph = StateGraph(UnifiedAgentState)
    graph.add_node('ensure_request', _ensure_request)
    graph.add_node('classify', _classify)
    graph.add_node('prepare_travel_request', _prepare_travel_request)
    graph.add_node('extract_trip_profile', _extract_trip_profile_node)
    graph.add_node('build_route_context', _build_route_context_node)
    graph.add_node('decide_trip_type', _decide_trip_type_node)
    graph.add_node('fetch_route_options', _fetch_route_options_node)
    graph.add_node('fetch_poi_candidates', _fetch_poi_candidates_node)
    graph.add_node('rank_poi_candidates', _rank_poi_candidates_node)
    graph.add_node('build_daily_itinerary', _build_daily_itinerary_node)
    graph.add_node('finalize_response', _finalize_travel_response)
    graph.add_node('build_nearby', _build_nearby)
    graph.add_node('build_general', _build_general)
    graph.add_node('repair_travel', _repair_travel)
    graph.set_entry_point('ensure_request')
    graph.add_edge('ensure_request', 'classify')
    graph.add_conditional_edges('classify', _after_classify, {'travel_planning': 'prepare_travel_request', 'nearby_search': 'build_nearby', 'general_chat': 'build_general'})
    graph.add_edge('prepare_travel_request', 'extract_trip_profile')
    graph.add_edge('extract_trip_profile', 'build_route_context')
    graph.add_edge('build_route_context', 'decide_trip_type')
    graph.add_edge('decide_trip_type', 'fetch_route_options')
    graph.add_edge('fetch_route_options', 'fetch_poi_candidates')
    graph.add_edge('fetch_poi_candidates', 'rank_poi_candidates')
    graph.add_edge('rank_poi_candidates', 'build_daily_itinerary')
    graph.add_edge('build_daily_itinerary', 'finalize_response')
    graph.add_conditional_edges('finalize_response', _after_travel_reflect, {'repair_travel': 'repair_travel', 'end': END})
    graph.add_edge('repair_travel', END)
    graph.add_edge('build_nearby', END)
    graph.add_edge('build_general', END)
    return _AsyncGraphRunner(graph.compile())


unified_graph = build_unified_graph()
