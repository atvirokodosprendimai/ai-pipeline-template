from __future__ import annotations

from dataclasses import dataclass

from wgmesh_pipeline.graph.state import Decision, GraphState
from wgmesh_pipeline.risk import classify_risk


@dataclass(frozen=True)
class GateDecision:
    decision: Decision
    risk_tier: str
    reasons: tuple[str, ...]


def decide_gate(
    *,
    changed_files: list[str],
    diff: str,
    max_files: int,
    tests_passed: bool,
    sanitise_ok: bool,
    review_findings: list[dict],
) -> GateDecision:
    risk = classify_risk(changed_files, diff, max_files=max_files)
    reasons = list(risk.reasons)
    if not tests_passed:
        reasons.append("tests failed")
    if not sanitise_ok:
        reasons.append("sanitise failed")
    if any(finding.get("blocking", False) for finding in review_findings):
        reasons.append("blocking review finding")

    if risk.high or reasons:
        return GateDecision(decision="escalate", risk_tier=risk.tier, reasons=tuple(reasons))
    return GateDecision(decision="merge", risk_tier="low", reasons=())


def gate_node(state: GraphState, *, max_files: int) -> GraphState:
    next_state = dict(state)
    _visit(next_state, "gate")
    decision = decide_gate(
        changed_files=list(next_state.get("changed_files", [])),
        diff=next_state.get("diff", ""),
        max_files=max_files,
        tests_passed=bool(next_state.get("tests_passed", False)),
        sanitise_ok=bool(next_state.get("sanitise_ok", False)),
        review_findings=list(next_state.get("review_findings", [])),
    )
    next_state["decision"] = decision.decision
    next_state["risk_tier"] = decision.risk_tier
    next_state["risk_reasons"] = list(decision.reasons)

    client = next_state.get("github")
    if client is not None:
        if decision.decision == "merge":
            client.merge_pr(int(next_state.get("impl_pr", 0)), commit_title=f"Merge issue #{next_state['issue'].number}")
        else:
            client.add_label(next_state["issue"].number, "needs-human")
    return next_state


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)

