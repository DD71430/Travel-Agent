from __future__ import annotations

from travel_agent.agent.workflow import AgentWorkflow


class AgentGraph(AgentWorkflow):
    pass


def build_graph() -> AgentGraph:
    return AgentGraph()
