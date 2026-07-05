from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from travel_agent.models.travel import TravelPlanRequest
from travel_agent.services.chat_planner import (
    ChatRequest,
    build_general_response,
    build_travel_request,
    classify_chat_intent,
    generate_general_answer,
)
from travel_agent.services.travel_planner import build_travel_plan


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
    route_reply: dict[str, Any]
    nearby_context: dict[str, Any]
    hotel_candidates: list[dict[str, str]]
    food_candidates: list[dict[str, str]]
    poi_candidates: list[dict[str, str]]


def _ensure_request(state: UnifiedAgentState) -> UnifiedAgentState:
    request = state['request']
    conversation_id = request.conversation_id or state.get('conversation_id') or 'default'
    if request.conversation_id != conversation_id:
        request = ChatRequest(**{**request.model_dump(), 'conversation_id': conversation_id})
    return {**state, 'request': request, 'conversation_id': conversation_id, 'iteration': int(state.get('iteration', 0) or 0), 'processing_notes': state.get('processing_notes', []) or []}


def _classify(state: UnifiedAgentState) -> UnifiedAgentState:
    request = state['request']
    intent = classify_chat_intent(request.question)
    notes = [*state.get('processing_notes', []), f'intent={intent}']
    return {**state, 'intent': intent, 'processing_notes': notes}


def _prepare_travel_request(state: UnifiedAgentState) -> UnifiedAgentState:
    travel_request = build_travel_request(state['request'])
    notes = [*state.get('processing_notes', []), 'travel_request_built']
    return {**state, 'travel_request': travel_request, 'processing_notes': notes}


def _build_travel(state: UnifiedAgentState) -> UnifiedAgentState:
    travel_request = state['travel_request']
    travel_plan = build_travel_plan(travel_request)
    response = {
        'conversation_id': travel_plan.conversation_id,
        'answer_type': 'travel_planning',
        'final_answer': travel_plan.summary,
        'data': {'travel_plan': travel_plan.model_dump()},
        'travel_request': travel_request.model_dump(),
        'upload_context': state.get('upload_context'),
        'meta': {'source': travel_plan.data_source, 'notes': state.get('processing_notes', [])},
        'error': travel_plan.route_error,
    }
    return {
        **state,
        'conversation_id': travel_plan.conversation_id,
        'answer_type': 'travel_planning',
        'final_answer': travel_plan.summary,
        'route_summary': travel_plan.summary,
        'data': response['data'],
        'meta': response['meta'],
        'error': response['error'],
        'response': response,
    }


def _prepare_nearby(state: UnifiedAgentState) -> UnifiedAgentState:
    from travel_agent.api.chat import _resolve_query_city, _resolve_nearby_anchor

    request = state['request']
    city = _resolve_query_city(request)
    anchor, anchor_point, anchor_debug = _resolve_nearby_anchor(request.question, city)
    nearby_context = {
        'city': city,
        'anchor': anchor,
        'anchor_point': anchor_point,
        'anchor_debug': anchor_debug,
    }
    notes = [*state.get('processing_notes', []), f'nearby_anchor={anchor}']
    return {**state, 'nearby_context': nearby_context, 'processing_notes': notes}


def _search_nearby_hotels(state: UnifiedAgentState) -> UnifiedAgentState:
    from travel_agent.api.chat import _search_nearby_category

    context = state.get('nearby_context', {})
    candidates, debug = _search_nearby_category('酒店', str(context.get('anchor') or ''), context.get('anchor_point'), str(context.get('city') or ''))
    return {**state, 'hotel_candidates': candidates, 'nearby_hotel_debug': debug, 'processing_notes': [*state.get('processing_notes', []), f'hotels={len(candidates)}']}


def _search_nearby_foods(state: UnifiedAgentState) -> UnifiedAgentState:
    from travel_agent.api.chat import _search_nearby_category

    context = state.get('nearby_context', {})
    candidates, debug = _search_nearby_category('餐厅', str(context.get('anchor') or ''), context.get('anchor_point'), str(context.get('city') or ''))
    return {**state, 'food_candidates': candidates, 'nearby_food_debug': debug, 'processing_notes': [*state.get('processing_notes', []), f'foods={len(candidates)}']}


def _search_nearby_pois(state: UnifiedAgentState) -> UnifiedAgentState:
    from travel_agent.api.chat import _search_nearby_category

    context = state.get('nearby_context', {})
    candidates, debug = _search_nearby_category('景点', str(context.get('anchor') or ''), context.get('anchor_point'), str(context.get('city') or ''))
    return {**state, 'poi_candidates': candidates, 'nearby_poi_debug': debug, 'processing_notes': [*state.get('processing_notes', []), f'pois={len(candidates)}']}


def _build_nearby(state: UnifiedAgentState) -> UnifiedAgentState:
    context = state.get('nearby_context', {})
    hotel_candidates = state.get('hotel_candidates', [])
    food_candidates = state.get('food_candidates', [])
    poi_candidates = state.get('poi_candidates', [])
    city = str(context.get('city') or '目标城市')
    anchor = str(context.get('anchor') or city)
    attraction_recommendations = []
    for item in poi_candidates[:6]:
        label = item.get('name', '')
        if item.get('address'):
            label = f"{label}（{item.get('address')}）"
        if label:
            attraction_recommendations.append(label)
    if not attraction_recommendations:
        attraction_recommendations = [f'{city}热门景点', f'{city}博物馆', f'{city}公园']
    hotel_preview = '；'.join(
        f"{item.get('name')}{f'（{item.get('address')}）' if item.get('address') else ''}"
        for item in hotel_candidates[:3]
        if item.get('name')
    )
    food_preview = '；'.join(
        f"{item.get('name')}{f'（{item.get('address')}）' if item.get('address') else ''}"
        for item in food_candidates[:3]
        if item.get('name')
    )
    poi_preview = '；'.join(attraction_recommendations[:4])
    final_answer_parts = [f'已识别为周边查询，将优先返回{anchor}附近的酒店、餐厅和景点候选。']
    if hotel_preview:
        final_answer_parts.append(f'酒店候选：{hotel_preview}')
    if food_preview:
        final_answer_parts.append(f'餐厅候选：{food_preview}')
    if poi_preview:
        final_answer_parts.append(f'景点候选：{poi_preview}')
    debug = {
        'city': city,
        'anchor': anchor,
        'anchor_point': context.get('anchor_point'),
        'anchor_debug': context.get('anchor_debug'),
        'hotel_count': len(hotel_candidates),
        'food_count': len(food_candidates),
        'poi_count': len(poi_candidates),
        'hotel_debug': state.get('nearby_hotel_debug'),
        'food_debug': state.get('nearby_food_debug'),
        'poi_debug': state.get('nearby_poi_debug'),
    }
    response = {
        'conversation_id': state.get('conversation_id', 'default'),
        'answer_type': 'nearby_search',
        'final_answer': '\n'.join(final_answer_parts),
        'data': {
            'nearby': {
                'city': city,
                'anchor': anchor,
                'anchor_point': context.get('anchor_point'),
                'anchor_debug': context.get('anchor_debug'),
                'destination_point': context.get('anchor_point'),
                'attraction_recommendations': attraction_recommendations,
                'transportation_suggestion': [
                    f'优先以{anchor}为中心搜索周边酒店、餐厅和景点',
                    '若未识别到具体地点，将回退到城市中心范围搜索',
                ],
                'hotel_candidates': hotel_candidates,
                'food_candidates': food_candidates,
                'debug': debug,
            }
        },
        'travel_request': None,
        'upload_context': state.get('upload_context'),
        'meta': {'source': 'poi_search', 'notes': state.get('processing_notes', []), 'debug': debug},
        'error': None,
    }
    return {**state, 'answer_type': response['answer_type'], 'final_answer': response['final_answer'], 'data': response['data'], 'meta': response['meta'], 'error': response['error'], 'response': response}


async def _build_general(state: UnifiedAgentState) -> UnifiedAgentState:
    response = build_general_response(state['request'])
    response['upload_context'] = state.get('upload_context')
    response['final_answer'] = await generate_general_answer(state['request'].question, state['conversation_id'])
    response.setdefault('meta', {})
    response['meta']['notes'] = state.get('processing_notes', [])
    return {**state, 'answer_type': response['answer_type'], 'final_answer': response['final_answer'], 'data': response['data'], 'meta': response['meta'], 'error': response['error'], 'response': response}


def _after_classify(state: UnifiedAgentState) -> str:
    return state.get('intent', 'general_chat')


def _after_travel_reflect(state: UnifiedAgentState) -> str:
    if state.get('error'):
        return 'repair_travel'
    if not state.get('final_answer'):
        return 'repair_travel'
    return 'end'


def _repair_travel(state: UnifiedAgentState) -> UnifiedAgentState:
    notes = [*state.get('processing_notes', []), f'repair:{state.get("retry_reason") or state.get("error") or "unknown"}']
    response = state.get('response') or {}
    response['meta'] = {**response.get('meta', {}), 'notes': notes}
    response['final_answer'] = response.get('final_answer') or state.get('route_summary') or '暂无答案'
    return {**state, 'processing_notes': notes, 'response': response, 'final_answer': response['final_answer'], 'error': None}


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
    graph.add_node('build_travel', _build_travel)
    graph.add_node('repair_travel', _repair_travel)
    graph.add_node('prepare_nearby', _prepare_nearby)
    graph.add_node('search_nearby_hotels', _search_nearby_hotels)
    graph.add_node('search_nearby_foods', _search_nearby_foods)
    graph.add_node('search_nearby_pois', _search_nearby_pois)
    graph.add_node('build_nearby', _build_nearby)
    graph.add_node('build_general', _build_general)
    graph.set_entry_point('ensure_request')
    graph.add_edge('ensure_request', 'classify')
    graph.add_conditional_edges('classify', _after_classify, {
        'travel_planning': 'prepare_travel_request',
        'nearby_search': 'prepare_nearby',
        'general_chat': 'build_general',
    })
    graph.add_edge('prepare_travel_request', 'build_travel')
    graph.add_edge('prepare_nearby', 'search_nearby_hotels')
    graph.add_edge('search_nearby_hotels', 'search_nearby_foods')
    graph.add_edge('search_nearby_foods', 'search_nearby_pois')
    graph.add_edge('search_nearby_pois', 'build_nearby')
    graph.add_conditional_edges('build_travel', _after_travel_reflect, {
        'repair_travel': 'repair_travel',
        'end': END,
    })
    graph.add_edge('repair_travel', END)
    graph.add_edge('build_nearby', END)
    graph.add_edge('build_general', END)
    return _AsyncGraphRunner(graph.compile())


unified_graph = build_unified_graph()
