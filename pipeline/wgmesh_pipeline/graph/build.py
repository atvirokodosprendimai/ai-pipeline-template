from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.graph.nodes.gate import gate_node
from wgmesh_pipeline.graph.nodes.implement import implement_node
from wgmesh_pipeline.graph.nodes.review import review_node
from wgmesh_pipeline.graph.nodes.spec import spec_node
from wgmesh_pipeline.graph.nodes.spec_pr import spec_pr_node
from wgmesh_pipeline.graph.nodes.triage import triage_node
from wgmesh_pipeline.graph.state import GraphState
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

        current = self.spec(current)
        current = self.spec_pr(current)
        if self.config.mode == "spec-only":
            return current
        current = self.implement(current)
        current = self.review(current)
        return self.gate(current, max_files=self.config.max_files)


def build_graph(config: Config) -> CompiledGraph:
    return CompiledGraph(
        config=config,
        triage=trace_node("triage", triage_node),
        spec=trace_node("spec", spec_node),
        spec_pr=trace_node("spec_pr", spec_pr_node),
        implement=trace_node("implement", implement_node),
        review=trace_node("review", review_node),
        gate=gate_node,
    )
