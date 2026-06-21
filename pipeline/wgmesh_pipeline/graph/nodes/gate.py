from __future__ import annotations

import logging
from dataclasses import dataclass

from wgmesh_pipeline.graph.state import Decision, GraphState
from wgmesh_pipeline.paywall import detect_component_paywall
from wgmesh_pipeline.risk import classify_risk

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateDecision:
    decision: Decision
    risk_tier: str
    reasons: tuple[str, ...]
    retryable: bool = False


def decide_gate(
    *,
    changed_files: list[str],
    diff: str,
    max_files: int,
    tests_passed: bool,
    sanitise_ok: bool,
    review_findings: list[dict],
    paywall_ok: bool = True,
    pii_ok: bool = True,
    emit_sanitise_ok: bool = True,
) -> GateDecision:
    risk = classify_risk(changed_files, diff, max_files=max_files)
    reasons = list(risk.reasons)
    if not tests_passed:
        reasons.append("tests failed")
    if not sanitise_ok:
        reasons.append("sanitise failed")
    if not pii_ok:
        reasons.append("PII check failed")
    if not emit_sanitise_ok:
        reasons.append("emit-sanitise failed")
    if not paywall_ok:
        reasons.append("component paywall")
    if any(finding.get("blocking", False) for finding in review_findings):
        reasons.append("blocking review finding")

    if risk.high or reasons:
        retryable_reasons = {"tests failed", "blocking review finding"}
        retryable = (
            risk.tier == "low"
            and sanitise_ok
            and paywall_ok
            and set(reasons).issubset(retryable_reasons)
        )
        return GateDecision(
            decision="escalate",
            risk_tier=risk.tier,
            reasons=tuple(reasons),
            retryable=retryable,
        )
    return GateDecision(decision="merge", risk_tier="low", reasons=(), retryable=False)


def gate_node(
    state: GraphState, *, max_files: int, apply_side_effects: bool = True
) -> GraphState:
    next_state = dict(state)
    _visit(next_state, "gate")
    diff = next_state.get("diff", "")
    changed_files = list(next_state.get("changed_files", []))
    try:
        paywall_ok, paywall_reasons = detect_component_paywall(
            diff=diff,
            changed_files=changed_files,
            spec_content=next_state.get("spec_content", ""),
        )
    except Exception:
        log.warning("gate: component paywall detection failed closed", exc_info=True)
        paywall_ok = False
        paywall_reasons = ["component paywall detector failed"]
    if not paywall_ok and paywall_reasons:
        next_state["paywall_reasons"] = paywall_reasons
    decision = decide_gate(
        changed_files=changed_files,
        diff=diff,
        max_files=max_files,
        tests_passed=bool(next_state.get("tests_passed", False)),
        sanitise_ok=bool(next_state.get("sanitise_ok", False)),
        paywall_ok=paywall_ok,
        review_findings=list(next_state.get("review_findings", [])),
        # The guards node (#1599 Phase D) is the always-on producer of these on
        # the live reviewed path and sets explicit booleans (False on any guard
        # failure). Default True covers shadow/synthetic paths where guards did
        # not run, so it never blocks them spuriously.
        pii_ok=bool(next_state.get("pii_ok", True)),
        emit_sanitise_ok=bool(next_state.get("emit_sanitise_ok", True)),
    )
    next_state["decision"] = decision.decision
    next_state["risk_tier"] = decision.risk_tier
    next_state["risk_reasons"] = list(decision.reasons)
    next_state["retryable"] = decision.retryable

    if apply_side_effects:
        apply_gate_side_effects(next_state)
    return next_state


def apply_gate_side_effects(state: GraphState) -> None:
    client = state.get("github")
    if client is None:
        return
    if state["decision"] == "merge":
        impl_pr = state.get("impl_pr")
        if impl_pr is None:
            raise RuntimeError("cannot merge implementation without impl_pr")
        # Judge-gated automerge (U4): the box no longer self-merges (which
        # required a non-author approval it can't supply — every impl PR
        # escalated, layer 3 of the convergence stall). It enables GitHub
        # auto-merge; the wgmesh protect-main ruleset gates the merge on the
        # impl-judge fail-closed CI check (+ build + status), so the PR merges
        # only when the judge passes — no approval, no reviewer PAT.
        # enable_auto_merge is mode-gated (shadow -> dry-run; spec-only ->
        # blocked). The poller parks the issue in awaiting_merge and completes it
        # to merged only on the real merge — never here (no phantom completion).
        client.enable_auto_merge(int(impl_pr))
    else:
        client.add_label(state["issue"].number, "needs-human")


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)
