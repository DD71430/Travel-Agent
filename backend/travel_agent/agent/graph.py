"""Deprecated AgentGraph alias. Use travel_graph.unified_graph instead."""

from __future__ import annotations

from travel_agent.agent.workflow import AgentWorkflow


class AgentGraph(AgentWorkflow):
    pass


def build_graph() -> AgentGraph:
    return AgentGraph()
