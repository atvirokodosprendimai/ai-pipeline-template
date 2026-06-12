"""Self-Heal detectors: the three stale sweeps, the circuit breaker, and the
fulfilled-needs-human close (cutover U4). Pure decisions — no forge writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from wgmesh_pipeline.selfheal.models import (
    CIRCUIT_MAX_CREATES,
    CIRCUIT_MAX_ERRORS,
    ESCALATE_COOLDOWN_HOURS,
    MAX_RETRIES_BEFORE_ESCALATE,
    HealAction,
    SelfHealInputs,
    SweepOutcome,
    audit_entry,
    first_timestamp,
    labels_joined,
    shift,
    tracker_entry,
)


@dataclass(frozen=True)
class _StaleSpec:
    """Per-sweep constants for the shared stale engine."""

    timestamp_keys: tuple[str, ...]
    cutoff_hours: int
    tracker_prefix: str
    heal_kind: str
    heal_reason: str
    remove_label: str
    add_label: str
    target: str
    escalate_title: str  # format with {n}
    escalate_body: str  # format with {n} and {r}
    escalate_reason: str


_TRIAGE = _StaleSpec(
    timestamp_keys=("createdAt", "created_at"), cutoff_hours=24, tracker_prefix="",
    heal_kind="retrigger_triage", heal_reason="stale >24h at needs-triage",
    remove_label="needs-triage", add_label="needs-triage", target="issue",
    escalate_title="[needs-human] Stuck at triage: #{n}",
    escalate_body="Self-healing failed to resolve stale triage for #{n} after {r} attempts.",
    escalate_reason="2 consecutive triage failures",
)
_COPILOT = _StaleSpec(
    timestamp_keys=("createdAt", "created_at"), cutoff_hours=48, tracker_prefix="",
    heal_kind="retrigger_copilot", heal_reason="stale >48h at copilot-triaging",
    remove_label="copilot-triaging", add_label="needs-triage", target="issue",
    escalate_title="[needs-human] Stuck at copilot-triaging: #{n}",
    escalate_body=(
        "Self-healing failed to resolve stale copilot-triaging for #{n} after {r} attempts."
    ),
    escalate_reason="2 consecutive copilot-triaging failures",
)
_APPROVED = _StaleSpec(
    timestamp_keys=("updatedAt", "updated_at"), cutoff_hours=24, tracker_prefix="pr-",
    heal_kind="retrigger_goose", heal_reason="stale >24h at approved-for-build",
    remove_label="approved-for-build", add_label="approved-for-build", target="pr",
    escalate_title="[needs-human] Stuck at build: PR #{n}",
    escalate_body=(
        "Self-healing failed to resolve stale approved-for-build PR #{n} after {r} attempts."
    ),
    escalate_reason="2 consecutive build trigger failures",
)

_Skip = Callable[[Mapping[str, Any]], bool]


def _sweep_stale(
    items: tuple[Mapping[str, Any], ...],
    spec: _StaleSpec,
    retry_tracker: Mapping[str, Any],
    inputs: SelfHealInputs,
    pre_count_skip: _Skip,
    post_count_skip: _Skip,
) -> SweepOutcome:
    """Shared stale engine — exact port of one workflow sweep step.

    Ordering parity: manual-only (+ ``pre_count_skip``) before the stale
    count; ``post_count_skip`` (in-progress spec/impl PR) after it; then
    cooldown (ISO string compare, as the shell ``\\<``), then
    escalate-after-2, else heal (label toggle). Heal REPLACES the tracker
    entry (dropping any cooldown_until); escalate only sets cooldown_until.
    """
    now, run_id = inputs.now, inputs.run_id
    if inputs.cutoff_override_minutes is not None:
        cutoff = shift(now, minutes=-inputs.cutoff_override_minutes)
    else:
        cutoff = shift(now, hours=-spec.cutoff_hours)
    tracker = dict(retry_tracker)
    actions: list[HealAction] = []
    audit: list[dict[str, Any]] = []
    stale = taken = created = 0

    for item in items:
        if first_timestamp(item, spec.timestamp_keys) >= cutoff:
            continue  # jq: select(.created/updatedAt < cutoff)
        number = int(item["number"])
        labels = labels_joined(item)
        if "manual-only" in labels or pre_count_skip(item):
            continue
        stale += 1
        if post_count_skip(item):
            continue
        key = f"{spec.tracker_prefix}{number}"
        entry = tracker_entry(tracker, key)
        retries = int(entry.get("retries") or 0)
        cooldown = str(entry.get("cooldown_until") or "")
        if cooldown and now < cooldown:
            continue
        if retries >= MAX_RETRIES_BEFORE_ESCALATE:
            actions.append(HealAction(
                kind="escalate", number=number, target=spec.target,
                title=spec.escalate_title.format(n=number),
                body=spec.escalate_body.format(n=number, r=retries),
                add_label="needs-human", reason=spec.escalate_reason,
            ))
            created += 1
            taken += 1
            tracker[key] = {**entry, "cooldown_until": shift(now, hours=ESCALATE_COOLDOWN_HOURS)}
            audit.append(audit_entry(
                now, run_id, "escalate", number, spec.escalate_reason, retries
            ))
            continue
        actions.append(HealAction(
            kind=spec.heal_kind, number=number, target=spec.target,
            remove_label=spec.remove_label, add_label=spec.add_label,
            reason=spec.heal_reason,
        ))
        taken += 1
        tracker[key] = {"retries": retries + 1, "last_retry": now, "action": spec.heal_kind}
        audit.append(audit_entry(
            now, run_id, spec.heal_kind, number, spec.heal_reason, retries + 1
        ))

    return SweepOutcome(
        actions=tuple(actions), audit=tuple(audit), retry_tracker=tracker,
        stale_found=stale, actions_taken=taken, issues_created=created,
    )


def sweep_stale_triage(inputs: SelfHealInputs, tracker: Mapping[str, Any]) -> SweepOutcome:
    """Stale needs-triage sweep (24h). Exclusion labels and the merged
    spec/impl-PR completion check skip BEFORE the stale count (cf. #540)."""
    def pre(item: Mapping[str, Any]) -> bool:
        labels = labels_joined(item)
        if "wont-do" in labels or "needs-info" in labels:
            return True
        return int(item["number"]) in inputs.merged_resolution_issues

    return _sweep_stale(
        inputs.stale_triage_issues, _TRIAGE, tracker, inputs, pre, lambda item: False
    )


def sweep_stale_copilot(inputs: SelfHealInputs, tracker: Mapping[str, Any]) -> SweepOutcome:
    """Stale copilot-triaging sweep (48h); spec-PR-in-progress skips after count."""
    return _sweep_stale(
        inputs.stale_copilot_issues, _COPILOT, tracker, inputs,
        lambda item: False,
        lambda item: int(item["number"]) in inputs.open_spec_pr_issues,
    )


def sweep_stale_approved(inputs: SelfHealInputs, tracker: Mapping[str, Any]) -> SweepOutcome:
    """Stale approved-for-build PR sweep (24h on updatedAt, tracker key pr-N);
    an open impl PR for the spec's issue number skips after the count."""
    def post(item: Mapping[str, Any]) -> bool:
        match = re.search(r"Issue #(\d+)", str(item.get("title") or ""))
        return bool(match) and int(match.group(1)) in inputs.open_impl_pr_issues

    return _sweep_stale(
        inputs.stale_approved_prs, _APPROVED, tracker, inputs, lambda item: False, post
    )


def circuit_breaker_tripped(issues_created: int, errors: int) -> bool:
    return issues_created >= CIRCUIT_MAX_CREATES or errors >= CIRCUIT_MAX_ERRORS


def circuit_breaker_action(issues_created: int, errors: int) -> HealAction:
    """The needs-human breaker issue (only the post-triage check creates it)."""
    return HealAction(
        kind="circuit_breaker", target="issue",
        title="[needs-human] Pipeline self-healing circuit breaker triggered",
        body=(
            f"Self-healing hit per-run limits: {issues_created} issues created, "
            f"{errors} errors. Manual review required."
        ),
        add_label="needs-human", reason="per-run limit exceeded",
    )


def _needs_human_resolution(item: Mapping[str, Any], inputs: SelfHealInputs) -> str | None:
    """Resolution reason for one needs-human issue, or None (signal order
    and the title-pattern elif chain ported exactly)."""
    number = int(item["number"])
    merged = int(inputs.linked_merged_pr_counts.get(number) or 0)
    if merged > 0:
        return f"Linked PR merged ({merged} merged PR(s) found)"
    title = str(item.get("title") or "").lower()
    if re.search(r"(api key|secret)", title):
        run_count = int(inputs.loop_state.get("run_count") or 0)
        if str(inputs.loop_state.get("last_run") or "") and run_count > 0:
            return f"Observation loop running successfully (run_count={run_count})"
    elif re.search(r"(health|endpoint)", title):
        if inputs.endpoints and all(
            200 <= int(e.get("status") or 0) < 400 for e in inputs.endpoints
        ):
            return "All health endpoints responding OK"
    elif re.search(r"(burn|capital|budget)", title):
        capital = (inputs.costs.get("runway") or {}).get("available_capital") or 0
        if isinstance(capital, int) and capital > 0:  # shell -gt is integer-only
            return f"Costs data populated (available_capital={capital})"
    return None


def sweep_needs_human(inputs: SelfHealInputs) -> SweepOutcome:
    """Close fulfilled needs-human issues (resolution signals 1 + 2)."""
    actions: list[HealAction] = []
    audit: list[dict[str, Any]] = []
    closed = 0
    for item in inputs.needs_human_issues or ():
        if "manual-only" in labels_joined(item):
            continue
        reason = _needs_human_resolution(item, inputs)
        if reason is None:
            continue
        number = int(item["number"])
        actions.append(HealAction(
            kind="close_needs_human", number=number, target="issue",
            comment=f"Resolved by self-healing: {reason}", reason=reason,
        ))
        closed += 1
        audit.append(audit_entry(
            inputs.now, inputs.run_id, "close_needs_human", number, reason, None
        ))
    return SweepOutcome(
        actions=tuple(actions), audit=tuple(audit), closed=closed, actions_taken=closed
    )
