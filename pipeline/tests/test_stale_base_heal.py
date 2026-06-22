"""Pure stale-base-heal planner (plan_stale_base_heal). No I/O, NoCallForge."""

from __future__ import annotations

from wgmesh_pipeline.selfheal import (
    CONFLICT_ESCALATE_COOLDOWN_HOURS,
    HEAL_KIND_STALE_BASE_REBASE,
    plan_stale_base_heal,
)
from wgmesh_pipeline.selfheal.models import parse_iso

NOW = "2026-06-21T12:00:00Z"
FUTURE = "2026-06-21T18:00:00Z"  # > NOW: an active cooldown
PAST = "2026-06-21T06:00:00Z"  # < NOW: an expired cooldown


def pr(
    number: int,
    head: str,
    mergeable: str | None,
    *,
    behind_by: int = 1,
    failing: bool = True,
) -> dict:
    return {
        "number": number,
        "headRefName": head,
        "mergeable": mergeable,
        "behindBy": behind_by,
        "hasFailingCheck": failing,
    }


def kinds(plan) -> list[str]:
    return [a.kind for a in plan.actions]


def test_happy_stale_base_bot_pr_yields_one_rebase() -> None:
    plan = plan_stale_base_heal([pr(7, "bot/impl-7", "MERGEABLE")], {}, NOW)

    assert kinds(plan) == [HEAL_KIND_STALE_BASE_REBASE]
    assert plan.actions[0].number == 7
    assert plan.actions[0].target == "pr"
    # planner does NOT increment a rebase attempt (executor updates next cycle)
    assert plan.tracker == {}


def test_non_bot_branch_is_never_touched() -> None:
    plan = plan_stale_base_heal([pr(7, "feature/human-7", "MERGEABLE")], {}, NOW)

    assert plan.actions == ()


def test_conflicting_and_none_states_skip() -> None:
    prs = [
        pr(1, "bot/impl-1", "CONFLICTING"),  # conflict-heal's job
        pr(2, "bot/impl-2", None),  # GitHub still computing
    ]

    plan = plan_stale_base_heal(prs, {}, NOW)

    assert plan.actions == ()


def test_current_branch_not_behind_is_skipped() -> None:
    plan = plan_stale_base_heal(
        [pr(7, "bot/impl-7", "MERGEABLE", behind_by=0)], {}, NOW
    )

    assert plan.actions == ()


def test_green_pr_is_never_force_pushed() -> None:
    plan = plan_stale_base_heal(
        [pr(7, "bot/impl-7", "MERGEABLE", failing=False)], {}, NOW
    )

    assert plan.actions == ()


def test_active_cooldown_skips() -> None:
    tracker = {"pr-7": {"retries": 1, "cooldown_until": FUTURE}}

    plan = plan_stale_base_heal([pr(7, "bot/impl-7", "MERGEABLE")], tracker, NOW)

    assert plan.actions == ()
    # tracker passed through unchanged
    assert plan.tracker == tracker


def test_expired_cooldown_below_cap_rebases() -> None:
    tracker = {"pr-7": {"retries": 1, "cooldown_until": PAST}}

    plan = plan_stale_base_heal([pr(7, "bot/impl-7", "MERGEABLE")], tracker, NOW)

    assert kinds(plan) == [HEAL_KIND_STALE_BASE_REBASE]


def test_cap_reached_escalates_not_rebases() -> None:
    tracker = {"pr-7": {"retries": 2}}

    plan = plan_stale_base_heal([pr(7, "bot/impl-7", "MERGEABLE")], tracker, NOW)

    assert kinds(plan) == ["escalate"]
    action = plan.actions[0]
    assert action.add_label == "needs-human"
    assert action.comment and "human" in action.comment.lower()
    assert action.comment and "diff" in action.comment.lower()
    # escalation sets a fresh cooldown (CONFLICT_ESCALATE_COOLDOWN_HOURS)
    cooldown = plan.tracker["pr-7"]["cooldown_until"]
    delta_hours = (parse_iso(cooldown) - parse_iso(NOW)).total_seconds() / 3600
    assert delta_hours == CONFLICT_ESCALATE_COOLDOWN_HOURS


def test_below_cap_with_one_retry_still_rebases() -> None:
    tracker = {"pr-7": {"retries": 1}}

    plan = plan_stale_base_heal([pr(7, "bot/impl-7", "MERGEABLE")], tracker, NOW)

    assert kinds(plan) == [HEAL_KIND_STALE_BASE_REBASE]


def test_dry_run_is_surfaced_on_the_plan() -> None:
    plan = plan_stale_base_heal(
        [pr(7, "bot/impl-7", "MERGEABLE")], {}, NOW, dry_run=True
    )

    assert plan.dry_run is True
    # plan content is identical to a non-dry run (executor honors the flag)
    assert kinds(plan) == [HEAL_KIND_STALE_BASE_REBASE]


def test_input_order_is_preserved() -> None:
    prs = [
        pr(3, "bot/impl-3", "MERGEABLE"),
        pr(1, "bot/spec-1", "MERGEABLE"),
        pr(2, "bot/impl-2", "MERGEABLE"),
    ]

    plan = plan_stale_base_heal(prs, {}, NOW)

    assert [a.number for a in plan.actions] == [3, 1, 2]
