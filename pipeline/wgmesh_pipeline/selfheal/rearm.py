"""Check-rearm planner — pure decision for stuck-on-absent-required-check bot PRs.

A bot ``fix: Issue #N`` PR can go MERGEABLE + all-produced-checks-green yet be
blocked forever because a *required* status check (``impl-judge``) was never
produced: the PR predates the judge workflow, so no ``pull_request`` event ever
fired it. A required check that is **absent** is permanently pending — not red —
so GitHub auto-merge waits on a check that will never post and the PR dead-ends.

This planner decides, per PR, whether to re-arm (the executor enables auto-merge
and pushes an empty commit to fire ``pull_request: synchronize`` → the judge
runs → the required check posts) or, after repeated failures, to escalate. It is
the MERGEABLE-but-unjudged sibling of ``selfheal/conflict.py`` (which rescues the
CONFLICTING subset; its force-push re-arms the judge as a side effect, so this
planner only ever sees the PRs conflict-heal leaves behind).

Scope guard (R3): only ``bot/``-prefixed head branches are ever considered;
human PRs are never touched. ``mergeable`` anything but ``"MERGEABLE"`` (including
``None`` while GitHub computes) is a skip. A PR whose required check is already
present (PASS *or* FAIL) is skipped — a failing judge is a real impl problem, not
ours to re-fire.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from wgmesh_pipeline.selfheal.models import (
    CONFLICT_ESCALATE_COOLDOWN_HOURS,
    HEAL_KIND_CHECK_REARM,
    MAX_RETRIES_BEFORE_ESCALATE,
    CheckRearmPlan,
    HealAction,
    tracker_entry,
)
from wgmesh_pipeline.selfheal.retry_policy import apply_retry_gate

BOT_BRANCH_PREFIX = "bot/"
FIX_TITLE_PREFIX = "fix: Issue #"
MERGEABLE = "MERGEABLE"
DEFAULT_REQUIRED_CONTEXT = "impl-judge"


def plan_check_rearm(
    prs: Sequence[Mapping[str, Any]],
    tracker: Mapping[str, Any],
    now: str,
    *,
    required_context: str = DEFAULT_REQUIRED_CONTEXT,
    dry_run: bool = False,
    max_retries: int = MAX_RETRIES_BEFORE_ESCALATE,
    escalate_cooldown_hours: float = CONFLICT_ESCALATE_COOLDOWN_HOURS,
) -> CheckRearmPlan:
    """Plan re-arm/escalate actions for MERGEABLE bot ``fix:`` PRs whose required
    check is absent.

    ``prs`` are plain dicts carrying ``number``, ``headRefName``, ``title``,
    ``isDraft``, the tri-state ``mergeable`` and ``present_contexts`` (the set of
    check/status context names already on the PR head) the orchestrator resolved
    — the planner stays pure. Input order is preserved. Returns the planned
    actions plus the tracker the executor persists; ``dry_run`` is surfaced for
    the executor to honor (the plan is identical either way).
    """
    out_tracker: dict[str, Any] = dict(tracker)
    actions: list[HealAction] = []

    for pr in prs:
        head = str(pr.get("headRefName") or "")
        if not head.startswith(BOT_BRANCH_PREFIX):
            continue  # R3: never touch human PRs
        if pr.get("isDraft"):
            continue
        if pr.get("mergeable") != MERGEABLE:
            continue  # CONFLICTING (conflict-heal owns it) / None (computing) → skip
        title = str(pr.get("title") or "")
        if not title.startswith(FIX_TITLE_PREFIX):
            continue  # only the judge's own predicate (product impl PRs)
        present = pr.get("present_contexts") or frozenset()
        if required_context in present:
            continue  # already armed — judge ran (PASS or FAIL); not ours to re-fire

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
                    f"Merge-lane heal could not arm the required `{required_context}` "
                    f"check after {decision.retries} attempts. A human needs to look — "
                    f"the judge may be failing to run on this PR."
                ),
                reason=f"{max_retries} consecutive re-arm attempts without the check posting",
            ))
            out_tracker[key] = {**entry, "cooldown_until": decision.cooldown_until}
            continue
        # decision.kind == "act": below the cap → attempt a re-arm. The planner
        # does NOT record the attempt; the executor reports the outcome and the
        # next cycle's tracker reflects it. Preserve the entry for the executor.
        actions.append(HealAction(
            kind=HEAL_KIND_CHECK_REARM,
            number=number,
            target="pr",
            reason=f"MERGEABLE bot fix PR — required `{required_context}` check absent",
        ))

    return CheckRearmPlan(actions=tuple(actions), tracker=out_tracker, dry_run=dry_run)
