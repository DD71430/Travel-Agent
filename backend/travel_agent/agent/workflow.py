"""Deprecated compatibility workflow.

The API main path uses travel_agent.agent.travel_graph.unified_graph.
"""

from __future__ import annotations

from travel_agent.agent.executor import ExecutorNode
from travel_agent.agent.planner import PlannerNode
from travel_agent.agent.reflection import ReflectionNode
from travel_agent.agent.state import AgentState


class _AsyncWorkflowRunner:
    def __init__(self, planner: PlannerNode, executor: ExecutorNode, reflection: ReflectionNode) -> None:
        self.planner = planner
        self.executor = executor
        self.reflection = reflection

    def _run_once(self, state: AgentState) -> AgentState:
        state = self.planner(state)
        state = self.executor(state)
        state = self.reflection(state)
        state['final_answer'] = state.get('draft_answer', '暂无答案')
        return state

    def invoke(self, state: AgentState) -> AgentState:
        state = {**state, 'iteration': int(state.get('iteration', 0) or 0)}
        state = self._run_once(state)
        if not state.get('reflection_result', {}).get('pass', False) and state.get('iteration', 0) < 1:
            retry_reason = state.get('reflection_result', {}).get('reason', '需要重试')
            state = {**state, 'iteration': int(state.get('iteration', 0) or 0) + 1, 'retry_reason': retry_reason}
            state = self._run_once(state)
        state['final_answer'] = state.get('draft_answer', '暂无答案')
        return state

    async def ainvoke(self, state: AgentState) -> AgentState:
        return self.invoke(state)


class AgentWorkflow:
    def __init__(self) -> None:
        self.planner = PlannerNode()
        self.executor = ExecutorNode()
        self.reflection = ReflectionNode()
        self.runner = _AsyncWorkflowRunner(self.planner, self.executor, self.reflection)

    def invoke(self, state: AgentState) -> AgentState:
        return self.runner.invoke(state)

    async def ainvoke(self, state: AgentState) -> AgentState:
        return await self.runner.ainvoke(state)


def build_graph() -> AgentWorkflow:
    return AgentWorkflow()
