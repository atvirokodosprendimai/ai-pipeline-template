from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass, field
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
from wgmesh_pipeline.tracing import (
    _session_id_ctx,
    build_callback_handler,
    trace_node,
)


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
    raw_gate: Callable[..., GraphState]
    _stage_graphs: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _callback_handler: object | None = field(default=None, init=False, repr=False)
    _callback_handler_initialized: bool = field(default=False, init=False, repr=False)

    def invoke(self, state: GraphState) -> GraphState:
        issue = state.get("issue")
        issue_number = getattr(issue, "number", None)
        session_id = f"issue-{issue_number}" if issue_number is not None else None
        handler = self._callback_handler_for_invoke()
        cfg = {"callbacks": [handler]} if handler is not None else None
        with _session_id_ctx(session_id):
            return self.compiled.invoke(state, config=cfg)

    def _callback_handler_for_invoke(self) -> object | None:
        if not self._callback_handler_initialized:
            self._callback_handler_initialized = True
            try:
                self._callback_handler = build_callback_handler(self.config)
            except Exception:
                self._callback_handler = None
        return self._callback_handler

    def _run_stage(self, name: str, state: GraphState) -> GraphState:
        stage_graph = self._stage_graphs[name]
        issue = state.get("issue")
        issue_number = getattr(issue, "number", None)
        session_id = f"issue-{issue_number}" if issue_number is not None else None
        try:
            handler = self._callback_handler_for_invoke()
            cfg = {"callbacks": [handler]} if handler is not None else None
            session_ctx = _session_id_ctx(session_id)
            session_ctx.__enter__()
        except Exception:
            return stage_graph.invoke(state)

        try:
            result = stage_graph.invoke(state, config=cfg)
        except BaseException:
            exc_info = sys.exc_info()
            try:
                session_ctx.__exit__(*exc_info)
            except Exception:
                pass
            raise
        else:
            try:
                session_ctx.__exit__(None, None, None)
            except Exception:
                pass
            return result

    def evaluate_gate(self, state: GraphState) -> GraphState:
        parameters = inspect.signature(self.raw_gate).parameters
        if "apply_side_effects" in parameters:
            return self.raw_gate(
                state,
                max_files=self.config.max_files,
                apply_side_effects=False,
            )
        return self.raw_gate(state, max_files=self.config.max_files)

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

    gate = trace_node("gate", gate_node)

    def _compile_single(name: str, fn: Callable[[GraphState], GraphState]) -> Any:
        graph = StateGraph(GraphState)
        graph.add_node(name, fn)
        graph.set_entry_point(name)
        graph.add_edge(name, END)
        return graph.compile()

    wrapper = StateGraphWrapper(
        config=config,
        compiled=None,
        triage=lambda state: state,
        spec=lambda state: state,
        spec_pr=lambda state: state,
        implement=lambda state: state,
        review=lambda state: state,
        gate=gate,
        raw_gate=gate_node,
    )
    wrapper._stage_graphs = {
        "triage": _compile_single("triage", triage_node),
        "spec": _compile_single("spec", spec_node),
        "spec_pr": _compile_single("spec_pr", spec_pr_node),
        "implement": _compile_single("implement", implement_node),
        "review": _compile_single("review", review_node),
    }
    wrapper.triage = lambda state: wrapper._run_stage("triage", state)
    wrapper.spec = lambda state: wrapper._run_stage("spec", state)
    wrapper.spec_pr = lambda state: wrapper._run_stage("spec_pr", state)
    wrapper.implement = lambda state: wrapper._run_stage("implement", state)
    wrapper.review = lambda state: wrapper._run_stage("review", state)

    graph = StateGraph(GraphState)
    graph.add_node("triage", triage_node)
    graph.add_node("escalate", wrapper.escalate)
    graph.add_node("spec", spec_node)
    graph.add_node("spec_pr", spec_pr_node)
    graph.add_node("ladder_prep", wrapper.ladder_prep)
    graph.add_node("implement", implement_node)
    graph.add_node("review", review_node)
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
