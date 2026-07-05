from __future__ import annotations

from travel_agent.agent.state import AgentState


class ReflectionNode:
    def __call__(self, state: AgentState) -> AgentState:
        draft = state.get('draft_answer', '')
        image_context = state.get('image_context')
        route_summary = state.get('route_summary', '')
        passed = bool(draft.strip())
        reason = '回答完整' if passed else '回答缺失，需重试'
        if image_context and not draft:
            passed = False
        if route_summary and '未知' in route_summary:
            passed = False
            reason = '路线摘要仍包含未知信息，需要修复'
        return {**state, 'reflection_result': {'pass': passed, 'reason': reason}}
