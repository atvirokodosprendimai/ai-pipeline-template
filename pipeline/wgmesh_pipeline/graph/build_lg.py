from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.graph.nodes.gate import apply_gate_side_effects, gate_node
from wgmesh_pipeline.graph.nodes.implement import implement_node
from wgmesh_pipeline.graph.nodes.review import review_node
from wgmesh_pipeline.graph.nodes.spec import spec_node
from wgmesh_pipeline.graph.nodes.spec_pr import spec_pr_node
from wgmesh_pipeline.graph.nodes.triage import triage_node
from wgmesh_pipeline.graph.state import GraphState
from wgmesh_pipeline.models import ladder_length_for
from wgmesh_pipeline.tracing import trace_node


@dataclass
class StateGraphWrapper:
    config: Config
    compiled: Any
    triage: Callable[[GraphState], GraphState]
    spec: Callable[[GraphState], GraphState]
    spec_pr: Callable[[GraphState], GraphState]
    implement: Callable[[GraphState], GraphState]
    review: Callable[[GraphState], GraphState]
    gate: Callable[..., GraphState]

    def invoke(self, state: GraphState) -> GraphState:
        return self.compiled.invoke(state)

    def evaluate_gate(self, state: GraphState) -> GraphState:
        parameters = inspect.signature(self.gate).parameters
        if "apply_side_effects" in parameters:
            return self.gate(
                state,
                max_files=self.config.max_files,
                apply_side_effects=False,
            )
        return self.gate(state, max_files=self.config.max_files)

    def ladder_prep(self, state: GraphState) -> GraphState:
        current = dict(state)
        tier = int(current.get("escalation_tier", 0))
        attempts = int(current.get("escalation_attempts", 0))
        history = list(current.get("escalation_history", []))
        current["escalation_tier"] = tier
        current["escalation_attempts"] = attempts
        history.append(tier)
        current["escalation_history"] = list(history)
        return current

    def ladder_retry(self, state: GraphState) -> GraphState:
        current = dict(state)
        current["escalation_tier"] = int(current.get("escalation_tier", 0)) + 1
        current["escalation_attempts"] = int(current.get("escalation_attempts", 0)) + 1
        return current

    def side_effects(self, state: GraphState) -> GraphState:
        current = dict(state)
        apply_gate_side_effects(current)
        return current

    def escalate(self, state: GraphState) -> GraphState:
        current = dict(state)
        current["decision"] = "escalate"
        if current.get("github") is not None:
            current["github"].add_label(current["issue"].number, "needs-human")
        current.setdefault("visited", []).append("escalate")
        return current

    def route_after_triage(self, state: GraphState) -> str:
        if state.get("classification") in {"wont-do", "needs-info"}:
            return "escalate"
        return "spec"

    def route_after_spec_pr(self, state: GraphState) -> str:
        if self.config.mode == "spec-only":
            return "end"
        return "ladder_prep"

    def route_after_gate(self, state: GraphState) -> str:
        if state.get("decision") == "merge":
            return "side_effects"
        if self.can_retry(state):
            return "ladder_retry"
        return "side_effects"

    def can_retry(self, state: GraphState) -> bool:
        tier = int(state.get("escalation_tier", 0))
        attempts = int(state.get("escalation_attempts", 0))
        ladder_length = ladder_length_for(self.config.stage_routing, "implement")
        return (
            bool(state.get("retryable", False))
            and tier + 1 < ladder_length
            and attempts < self.config.max_escalation_attempts
        )


def build_state_graph(config: Config) -> StateGraphWrapper:
    from langgraph.graph import END, StateGraph

    triage = trace_node("triage", triage_node)
    spec = trace_node("spec", spec_node)
    spec_pr = trace_node("spec_pr", spec_pr_node)
    implement = trace_node("implement", implement_node)
    review = trace_node("review", review_node)

    wrapper = StateGraphWrapper(
        config=config,
        compiled=None,
        triage=triage,
        spec=spec,
        spec_pr=spec_pr,
        implement=implement,
        review=review,
        gate=gate_node,
    )

    graph = StateGraph(GraphState)
    graph.add_node("triage", wrapper.triage)
    graph.add_node("escalate", wrapper.escalate)
    graph.add_node("spec", wrapper.spec)
    graph.add_node("spec_pr", wrapper.spec_pr)
    graph.add_node("ladder_prep", wrapper.ladder_prep)
    graph.add_node("implement", wrapper.implement)
    graph.add_node("review", wrapper.review)
    graph.add_node("gate", wrapper.evaluate_gate)
    graph.add_node("ladder_retry", wrapper.ladder_retry)
    graph.add_node("side_effects", wrapper.side_effects)

    graph.set_entry_point("triage")
    graph.add_conditional_edges(
        "triage",
        wrapper.route_after_triage,
        {"escalate": "escalate", "spec": "spec"},
    )
    graph.add_edge("escalate", END)
    graph.add_edge("spec", "spec_pr")
    graph.add_conditional_edges(
        "spec_pr",
        wrapper.route_after_spec_pr,
        {"end": END, "ladder_prep": "ladder_prep"},
    )
    graph.add_edge("ladder_prep", "implement")
    graph.add_edge("implement", "review")
    graph.add_edge("review", "gate")
    graph.add_conditional_edges(
        "gate",
        wrapper.route_after_gate,
        {"side_effects": "side_effects", "ladder_retry": "ladder_retry"},
    )
    graph.add_edge("ladder_retry", "ladder_prep")
    graph.add_edge("side_effects", END)

    wrapper.compiled = graph.compile()
    return wrapper
