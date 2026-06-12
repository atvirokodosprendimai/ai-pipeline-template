"""Self-Heal thin runner (cutover U4): diagnose → plan heals → build state.

NO forge writes this phase — the runner returns the state dict plus the
planned actions; persisting state, the sanitise gate, and publishing the
actions stay with the caller.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from wgmesh_pipeline.forge.protocol import Forge
from wgmesh_pipeline.selfheal.models import (
    HealAction,
    SelfHealInputs,
    SelfHealRun,
    audit_entry,
)
from wgmesh_pipeline.selfheal.signals import (
    assert_state_mutation,
    build_state,
    check_funnel_signals,
    check_idle_signal,
    decide_idle_dispatch,
)
from wgmesh_pipeline.selfheal.sweeps import (
    circuit_breaker_action,
    circuit_breaker_tripped,
    sweep_needs_human,
    sweep_stale_approved,
    sweep_stale_copilot,
    sweep_stale_triage,
)


def needs_human_from_forge(forge: Forge) -> tuple[dict[str, Any], ...]:
    """Best-effort needs-human snapshot via existing Forge methods only
    (no timestamps needed for this sweep, so it is NOT degraded)."""
    return tuple(
        {"number": issue.number, "title": issue.title, "labels": list(issue.labels)}
        for issue in forge.list_open_issues()
        if "needs-human" in issue.labels and not issue.pull_request
    )


def run_self_heal(forge: Forge, inputs: SelfHealInputs) -> SelfHealRun:
    """Step order and circuit gating mirror the workflow exactly: triage
    sweep, breaker check (creates the breaker issue), copilot / approved /
    needs-human sweeps and funnel signals all gated on the breaker; the idle
    signal is computed unconditionally; the idle dispatch is gated; the state
    summary always lands; the mutation assertion runs last."""
    prev = inputs.previous_state
    tracker: Mapping[str, Any] = dict(prev.get("retry_tracker") or {})
    actions: list[HealAction] = []
    audit: list[dict[str, Any]] = []
    taken = errors = created = closed = 0
    found = {"triage": 0, "copilot": 0, "approved": 0}

    triage = sweep_stale_triage(inputs, tracker)
    tracker = triage.retry_tracker
    actions += triage.actions
    audit += triage.audit
    taken += triage.actions_taken
    errors += triage.errors
    created += triage.issues_created
    found["triage"] = triage.stale_found

    tripped = circuit_breaker_tripped(created, errors)
    if tripped:
        actions.append(circuit_breaker_action(created, errors))
        audit.append(audit_entry(
            inputs.now, inputs.run_id, "circuit_breaker", None,
            "per-run limit exceeded", None,
        ))

    if not tripped:
        copilot = sweep_stale_copilot(inputs, tracker)
        tracker = copilot.retry_tracker
        actions += copilot.actions
        audit += copilot.audit
        taken += copilot.actions_taken
        errors += copilot.errors
        created += copilot.issues_created
        found["copilot"] = copilot.stale_found
        tripped = circuit_breaker_tripped(created, errors)

    if not tripped:
        approved = sweep_stale_approved(inputs, tracker)
        tracker = approved.retry_tracker
        actions += approved.actions
        audit += approved.audit
        taken += approved.actions_taken
        errors += approved.errors
        created += approved.issues_created
        found["approved"] = approved.stale_found
        tripped = circuit_breaker_tripped(created, errors)

    funnel_signals = dict(prev.get("funnel_signals") or {})
    if not tripped:
        needs_human_inputs = inputs
        if inputs.needs_human_issues is None:
            needs_human_inputs = replace(
                inputs, needs_human_issues=needs_human_from_forge(forge)
            )
        humans = sweep_needs_human(needs_human_inputs)
        actions += humans.actions
        audit += humans.audit
        taken += humans.actions_taken
        errors += humans.errors
        closed += humans.closed
        funnel_signals, funnel_audit = check_funnel_signals(inputs)
        audit.append(funnel_audit)

    idle_signal = check_idle_signal(inputs, taken, errors)
    if not tripped:
        dispatch, idle_signal = decide_idle_dispatch(idle_signal, inputs.now)
        if dispatch is not None:
            actions.append(dispatch)

    state = build_state(
        prev, now=inputs.now, retry_tracker=tracker,
        funnel_signals=funnel_signals, idle_signal=idle_signal,
        stale_triage_found=found["triage"], stale_copilot_found=found["copilot"],
        stale_approved_found=found["approved"], needs_human_closed=closed,
        actions_taken=taken, errors=errors,
    )
    state, passed, dead = assert_state_mutation(
        str(prev.get("last_check") or ""), state, inputs.now
    )
    if dead is not None:
        actions.append(dead)
    return SelfHealRun(
        state=state, actions=tuple(actions), audit=tuple(audit),
        circuit_breaker_tripped=tripped, mutation_asserted=passed,
    )
