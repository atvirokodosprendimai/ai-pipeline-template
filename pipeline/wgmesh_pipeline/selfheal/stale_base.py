"""Stale-base-heal planner — pure decision for stale-base-broken bot PRs.

A bot PR (`bot/spec-*`, `bot/impl-*`) can be ``mergeable=MERGEABLE`` (no conflict)
yet have a FAILING check because its branch was cut before a since-merged fix to
``main`` — its tree is stale and the failure is already resolved on current main.
``conflict-heal`` only rebases CONFLICTING PRs, so these stay frozen. This planner
decides, per PR, whether to rebase (onto current main, so checks re-run against
the fixed tree) or escalate; the git/forge writes live in the workflow executor
(``company/scripts/stale-base-heal/``). Mirrors the ``selfheal/`` planning-vs-
execution split and the ``conflict.py`` shape — ``NoCallForge``-unit-testable.

Scope guards: only ``bot/``-prefixed head branches are ever considered (human PRs
are never touched). ``mergeable is None`` (GitHub still computing) and
``CONFLICTING`` (conflict-heal's job) are skipped. A PR is a candidate only when
it is BEHIND main (``behindBy > 0`` — a current branch needs no rebase) AND has a
failing check (``hasFailingCheck`` — a green PR must not be force-pushed; thrash
guard). Both signals are pre-resolved by the workflow so the planner stays pure.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from wgmesh_pipeline.selfheal.models import (
    CONFLICT_ESCALATE_COOLDOWN_HOURS,
    HEAL_KIND_STALE_BASE_REBASE,
    MAX_RETRIES_BEFORE_ESCALATE,
    HealAction,
    StaleBaseHealPlan,
    tracker_entry,
)
from wgmesh_pipeline.selfheal.retry_policy import apply_retry_gate

BOT_BRANCH_PREFIX = "bot/"
MERGEABLE = "MERGEABLE"


def plan_stale_base_heal(
    prs: Sequence[Mapping[str, Any]],
    tracker: Mapping[str, Any],
    now: str,
    *,
    dry_run: bool = False,
    max_retries: int = MAX_RETRIES_BEFORE_ESCALATE,
    escalate_cooldown_hours: float = CONFLICT_ESCALATE_COOLDOWN_HOURS,
) -> StaleBaseHealPlan:
    """Plan rebase/escalate actions for stale-base-broken MERGEABLE bot PRs.

    ``prs`` are plain dicts carrying ``number``, ``headRefName``, the tri-state
    ``mergeable`` (``"MERGEABLE"`` / ``"CONFLICTING"`` / ``None``), ``behindBy``
    (int commits behind ``origin/main``) and ``hasFailingCheck`` (bool) — all
    resolved by the workflow so the planner stays pure. Order is stable (input
    order preserved). Returns the planned actions plus the tracker the executor
    persists; ``dry_run`` is surfaced for the executor to honor (the plan itself
    is identical either way).
    """
    out_tracker: dict[str, Any] = dict(tracker)
    actions: list[HealAction] = []

    for pr in prs:
        head = str(pr.get("headRefName") or "")
        if not head.startswith(BOT_BRANCH_PREFIX):
            continue  # never touch human PRs
        if pr.get("mergeable") != MERGEABLE:
            continue  # CONFLICTING (conflict-heal's job) or None (computing) → skip
        if int(pr.get("behindBy") or 0) <= 0:
            continue  # already current → a rebase would be a no-op force-push
        if not bool(pr.get("hasFailingCheck")):
            continue  # green PR → never force-push it (thrash guard)
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
                    f"Stale-base-heal rebased this PR onto main "
                    f"{decision.retries} times and its checks still fail — the "
                    f"failure is in the PR's own diff, not a stale base. A human "
                    f"needs to fix or close it."
                ),
                reason="2 consecutive rebase attempts still red",
            ))
            out_tracker[key] = {**entry, "cooldown_until": decision.cooldown_until}
            continue
        # decision.kind == "act": below the cap → attempt a rebase. The planner
        # does NOT increment retries here; the executor reports success/failure
        # and the next cycle's tracker reflects it (R5: clean reset / failure
        # increment). Preserve the entry so the executor can update it.
        actions.append(HealAction(
            kind=HEAL_KIND_STALE_BASE_REBASE,
            number=number,
            target="pr",
        ))

    return StaleBaseHealPlan(
        actions=tuple(actions),
        tracker=out_tracker,
        dry_run=dry_run,
    )
