from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Callable

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.graph.nodes.gate import apply_gate_side_effects, gate_node
from wgmesh_pipeline.graph.nodes.implement import implement_node
from wgmesh_pipeline.graph.nodes.review import review_node
from wgmesh_pipeline.graph.nodes.spec import spec_node
from wgmesh_pipeline.graph.nodes.spec_pr import spec_pr_node
from wgmesh_pipeline.graph.nodes.surface_gate import run_surface_gate, surface_gate_blocks
from wgmesh_pipeline.graph.nodes.triage import triage_node
from wgmesh_pipeline.graph.state import GraphState
from wgmesh_pipeline.models import ladder_length_for
from wgmesh_pipeline.tracing import trace_node


@dataclass
class CompiledGraph:
    config: Config
    triage: Callable[[GraphState], GraphState] = triage_node
    spec: Callable[[GraphState], GraphState] = spec_node
    spec_pr: Callable[[GraphState], GraphState] = spec_pr_node
    implement: Callable[[GraphState], GraphState] = implement_node
    review: Callable[[GraphState], GraphState] = review_node
    gate: Callable[..., GraphState] = gate_node

    def invoke(self, state: GraphState) -> GraphState:
        current = self.triage(state)
        if current.get("classification") in {"wont-do", "needs-info"}:
            current = dict(current)
            current["decision"] = "escalate"
            if current.get("github") is not None:
                current["github"].add_label(current["issue"].number, "needs-human")
            current.setdefault("visited", []).append("escalate")
            return current

        # Surface gate (R2): a service or unclassified issue never reaches spec in
        # the wgmesh pipeline. Mirrors the wont-do/needs-info escape above —
        # park via needs-human (+ the persisted surface label) instead of building.
        current = run_surface_gate(current)
        if surface_gate_blocks(current):
            current = dict(current)
            current["decision"] = "escalate"
            if current.get("github") is not None:
                current["github"].add_label(current["issue"].number, "needs-human")
            current.setdefault("visited", []).append("escalate")
            return current

        current = self.spec(current)
        current = self.spec_pr(current)
        if self.config.mode == "spec-only":
            return current
        current = self._run_implementation_ladder(current)
        apply_gate_side_effects(current)
        return current

    def _run_implementation_ladder(self, state: GraphState) -> GraphState:
        current = dict(state)
        tier = int(current.get("escalation_tier", 0))
        attempts = int(current.get("escalation_attempts", 0))
        history = list(current.get("escalation_history", []))
        ladder_length = ladder_length_for(self.config.stage_routing, "implement")

        while True:
            current["escalation_tier"] = tier
            current["escalation_attempts"] = attempts
            history.append(tier)
            current["escalation_history"] = list(history)

            current = self.implement(current)
            current = self.review(current)
            current = self._evaluate_gate(current)

            if current.get("decision") == "merge":
                return current

            can_retry = (
                bool(current.get("retryable", False))
                and tier + 1 < ladder_length
                and attempts < self.config.max_escalation_attempts
            )
            if not can_retry:
                return current

            tier += 1
            attempts += 1
            current = dict(current)

    def _evaluate_gate(self, state: GraphState) -> GraphState:
        parameters = inspect.signature(self.gate).parameters
        if "apply_side_effects" in parameters:
            return self.gate(
                state,
                max_files=self.config.max_files,
                apply_side_effects=False,
            )
        return self.gate(state, max_files=self.config.max_files)


def build_graph(config: Config) -> object:
    if getattr(config, "graph_impl", "legacy") == "langgraph":
        from wgmesh_pipeline.graph.build_lg import build_state_graph

        return build_state_graph(config)

    return CompiledGraph(
        config=config,
        triage=trace_node("triage", triage_node),
        spec=trace_node("spec", spec_node),
        spec_pr=trace_node("spec_pr", spec_pr_node),
        implement=trace_node("implement", implement_node),
        review=trace_node("review", review_node),
        gate=gate_node,
    )
