"""Conflict-heal planner — pure decision for CONFLICTING bot PRs.

A bot PR (`bot/spec-*`, `bot/impl-*`) goes ``mergeable=CONFLICTING`` when ``main``
moves under it. The pipeline has no rebase capability, so such a PR dead-ends
(a CONFLICTING PR fires no ``pull_request`` workflows → the judge never runs).
This planner decides, per PR, whether to rebase or escalate; the git/forge writes
live in the workflow executor (``company/scripts/conflict-heal/``). Mirrors the
``selfheal/`` planning-vs-execution split — ``NoCallForge``-unit-testable.

Scope guard (R1/R4): only ``bot/``-prefixed head branches are ever considered;
human PRs are never touched. ``mergeable is None`` (GitHub still computing) is a
skip, never inferred as not-conflicting.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from wgmesh_pipeline.selfheal.models import (
    CONFLICT_ESCALATE_COOLDOWN_HOURS,
    HEAL_KIND_CONFLICT_REBASE,
    MAX_RETRIES_BEFORE_ESCALATE,
    ConflictHealPlan,
    HealAction,
    tracker_entry,
)
from wgmesh_pipeline.selfheal.retry_policy import apply_retry_gate

BOT_BRANCH_PREFIX = "bot/"
CONFLICTING = "CONFLICTING"


def plan_conflict_heal(
    prs: Sequence[Mapping[str, Any]],
    tracker: Mapping[str, Any],
    now: str,
    *,
    dry_run: bool = False,
    max_retries: int = MAX_RETRIES_BEFORE_ESCALATE,
    escalate_cooldown_hours: float = CONFLICT_ESCALATE_COOLDOWN_HOURS,
) -> ConflictHealPlan:
    """Plan rebase/escalate actions for CONFLICTING bot PRs.

    ``prs`` are plain dicts carrying ``number``, ``headRefName`` and the
    tri-state ``mergeable`` (``"CONFLICTING"`` / ``"MERGEABLE"`` / ``None``) the
    workflow already resolved via the forge accessor — the planner stays pure.
    Order is stable (input order preserved). Returns the planned actions plus
    the tracker the executor persists; ``dry_run`` is surfaced for the executor
    to honor (the plan itself is identical either way).
    """
    out_tracker: dict[str, Any] = dict(tracker)
    actions: list[HealAction] = []

    for pr in prs:
        head = str(pr.get("headRefName") or "")
        if not head.startswith(BOT_BRANCH_PREFIX):
            continue  # R1/R4: never touch human PRs
        if pr.get("mergeable") != CONFLICTING:
            continue  # MERGEABLE or None (still computing) → skip
        number = int(pr["number"])
        key = f"pr-{number}"
        entry = tracker_entry(out_tracker, key)
        decision = apply_retry_gate(
            entry,
            now,
            max_retries=max_retries,
            escalate_cooldown_hours=escalate_cooldown_hours,
        )
        if decision.kind == "skip":
            continue
        if decision.kind == "escalate":
            actions.append(HealAction(
                kind="escalate",
                number=number,
                target="pr",
                add_label="needs-human",
                comment=(
                    f"Conflict-heal could not rebase this PR after "
                    f"{decision.retries} attempts. A human needs to resolve the "
                    f"conflict or close it."
                ),
                reason="2 consecutive rebase failures",
            ))
            out_tracker[key] = {**entry, "cooldown_until": decision.cooldown_until}
            continue
        # decision.kind == "act": below the cap → attempt a rebase. The planner
        # does NOT increment retries here; the executor reports success/failure
        # and the next cycle's tracker reflects it (R5: clean reset / failure
        # increment). Preserve the entry so the executor can update it.
        actions.append(HealAction(
            kind=HEAL_KIND_CONFLICT_REBASE,
            number=number,
            target="pr",
            reason="CONFLICTING bot PR — rebase onto main",
        ))

    return ConflictHealPlan(actions=tuple(actions), tracker=out_tracker, dry_run=dry_run)
