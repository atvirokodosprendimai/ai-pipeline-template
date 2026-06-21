"""U1 — pure conflict-heal planner (plan_conflict_heal). No I/O, NoCallForge."""

from __future__ import annotations

from wgmesh_pipeline.selfheal import (
    CONFLICT_ESCALATE_COOLDOWN_HOURS,
    HEAL_KIND_CONFLICT_REBASE,
    plan_conflict_heal,
)
from wgmesh_pipeline.selfheal.models import parse_iso

NOW = "2026-06-21T12:00:00Z"
FUTURE = "2026-06-21T18:00:00Z"  # > NOW: an active cooldown
PAST = "2026-06-21T06:00:00Z"  # < NOW: an expired cooldown


def pr(number: int, head: str, mergeable: str | None) -> dict:
    return {"number": number, "headRefName": head, "mergeable": mergeable}


def kinds(plan) -> list[str]:
    return [a.kind for a in plan.actions]


def test_happy_one_conflicting_bot_pr_yields_one_rebase() -> None:
    plan = plan_conflict_heal([pr(7, "bot/impl-7", "CONFLICTING")], {}, NOW)

    assert kinds(plan) == [HEAL_KIND_CONFLICT_REBASE]
    assert plan.actions[0].number == 7
    assert plan.actions[0].target == "pr"
    # planner does NOT increment a rebase attempt (R5 — executor updates next cycle)
    assert plan.tracker == {}


def test_non_bot_branch_is_never_touched() -> None:
    plan = plan_conflict_heal([pr(7, "feature/human-7", "CONFLICTING")], {}, NOW)

    assert plan.actions == ()


def test_mergeable_and_none_states_skip() -> None:
    prs = [
        pr(1, "bot/impl-1", "MERGEABLE"),
        pr(2, "bot/impl-2", None),  # GitHub still computing
    ]

    plan = plan_conflict_heal(prs, {}, NOW)

    assert plan.actions == ()


def test_active_cooldown_skips() -> None:
    tracker = {"pr-7": {"retries": 1, "cooldown_until": FUTURE}}

    plan = plan_conflict_heal([pr(7, "bot/impl-7", "CONFLICTING")], tracker, NOW)

    assert plan.actions == ()
    # tracker passed through unchanged
    assert plan.tracker == tracker


def test_cap_reached_escalates_not_rebases() -> None:
    tracker = {"pr-7": {"retries": 2}}

    plan = plan_conflict_heal([pr(7, "bot/impl-7", "CONFLICTING")], tracker, NOW)

    assert kinds(plan) == ["escalate"]
    action = plan.actions[0]
    assert action.add_label == "needs-human"
    assert action.comment and "human" in action.comment.lower()
    # escalation sets a fresh 72h cooldown (CONFLICT_ESCALATE_COOLDOWN_HOURS)
    cooldown = plan.tracker["pr-7"]["cooldown_until"]
    delta_hours = (parse_iso(cooldown) - parse_iso(NOW)).total_seconds() / 3600
    assert delta_hours == CONFLICT_ESCALATE_COOLDOWN_HOURS


def test_below_cap_with_one_retry_still_rebases() -> None:
    tracker = {"pr-7": {"retries": 1}}

    plan = plan_conflict_heal([pr(7, "bot/impl-7", "CONFLICTING")], tracker, NOW)

    assert kinds(plan) == [HEAL_KIND_CONFLICT_REBASE]
    # entry preserved for the executor to update (not incremented by the planner)
    assert plan.tracker["pr-7"] == {"retries": 1}


def test_expired_cooldown_below_cap_rebases() -> None:
    tracker = {"pr-7": {"retries": 1, "cooldown_until": PAST}}

    plan = plan_conflict_heal([pr(7, "bot/impl-7", "CONFLICTING")], tracker, NOW)

    assert kinds(plan) == [HEAL_KIND_CONFLICT_REBASE]


def test_multiple_prs_mixed_states_stable_order() -> None:
    prs = [
        pr(1, "bot/impl-1", "CONFLICTING"),  # rebase
        pr(2, "feature/human-2", "CONFLICTING"),  # skip (human)
        pr(3, "bot/spec-3", "MERGEABLE"),  # skip
        pr(4, "bot/impl-4", "CONFLICTING"),  # escalate (cap)
        pr(5, "bot/impl-5", None),  # skip (computing)
    ]
    tracker = {"pr-4": {"retries": 2}}

    plan = plan_conflict_heal(prs, tracker, NOW)

    assert [(a.number, a.kind) for a in plan.actions] == [
        (1, HEAL_KIND_CONFLICT_REBASE),
        (4, "escalate"),
    ]


def test_dry_run_flag_surfaced_on_plan() -> None:
    plan = plan_conflict_heal(
        [pr(7, "bot/impl-7", "CONFLICTING")], {}, NOW, dry_run=True
    )

    assert plan.dry_run is True
    # actions are still produced (the executor honors dry_run, not the planner)
    assert kinds(plan) == [HEAL_KIND_CONFLICT_REBASE]


def test_planner_is_pure_no_input_mutation() -> None:
    tracker = {"pr-4": {"retries": 2}}
    snapshot = {"pr-4": {"retries": 2}}

    plan_conflict_heal([pr(4, "bot/impl-4", "CONFLICTING")], tracker, NOW)

    assert tracker == snapshot  # planner copied, never mutated the input
