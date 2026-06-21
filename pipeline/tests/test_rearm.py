"""U1 — check-rearm planner (rearm.py): pure decision for MERGEABLE bot fix PRs
whose required judge check is absent.

No I/O: the planner is fed plain dicts (the orchestrator resolves mergeable +
present contexts via gh) and a tracker, and returns planned actions + the
tracker to persist.
"""

from __future__ import annotations

from wgmesh_pipeline.selfheal import (
    HEAL_KIND_CHECK_REARM,
    MAX_RETRIES_BEFORE_ESCALATE,
    plan_check_rearm,
)

NOW = "2026-06-21T12:00:00Z"
REQUIRED = "impl-judge"


def _pr(number, head, *, title="fix: Issue #1 - do a thing", mergeable="MERGEABLE",
        is_draft=False, present=()):
    return {
        "number": number,
        "headRefName": head,
        "title": title,
        "isDraft": is_draft,
        "mergeable": mergeable,
        "present_contexts": frozenset(present),
    }


def _plan(prs, tracker=None, **kw):
    return plan_check_rearm(prs, tracker or {}, NOW, required_context=REQUIRED, **kw)


def test_mergeable_fix_pr_absent_check_is_rearmed() -> None:
    plan = _plan([_pr(782, "bot/impl-782", present=["build-and-push", "status-check"])])
    assert [a.kind for a in plan.actions] == [HEAL_KIND_CHECK_REARM]
    assert plan.actions[0].number == 782
    assert plan.actions[0].target == "pr"


def test_check_already_present_is_skipped() -> None:
    # judge ran (PASS or FAIL) — present means armed; not ours to re-fire.
    plan = _plan([_pr(782, "bot/impl-782", present=["impl-judge", "build-and-push"])])
    assert plan.actions == ()


def test_spec_pr_is_skipped() -> None:
    plan = _plan([_pr(784, "bot/spec-784", title="spec: Issue #783 - add widget")])
    assert plan.actions == ()


def test_human_pr_is_never_touched() -> None:
    # Eligible in every other way, but the head is not bot/* — R3 scope guard.
    plan = _plan([_pr(9, "feature/human-9", present=[])])
    assert plan.actions == ()


def test_draft_conflicting_and_unknown_mergeable_are_skipped() -> None:
    prs = [
        _pr(1, "bot/impl-1", is_draft=True),
        _pr(2, "bot/impl-2", mergeable="CONFLICTING"),
        _pr(3, "bot/impl-3", mergeable=None),
    ]
    assert _plan(prs).actions == ()


def test_cooldown_blocks_then_elapses() -> None:
    cooling = {"pr-782": {"retries": 1, "cooldown_until": "2026-06-21T18:00:00Z"}}
    assert _plan([_pr(782, "bot/impl-782")], cooling).actions == ()  # now < cooldown

    elapsed = {"pr-782": {"retries": 1, "cooldown_until": "2026-06-21T06:00:00Z"}}
    plan = _plan([_pr(782, "bot/impl-782")], elapsed)  # now > cooldown, below cap
    assert [a.kind for a in plan.actions] == [HEAL_KIND_CHECK_REARM]


def test_at_cap_escalates_once() -> None:
    at_cap = {"pr-782": {"retries": MAX_RETRIES_BEFORE_ESCALATE}}
    plan = _plan([_pr(782, "bot/impl-782")], at_cap)
    assert [a.kind for a in plan.actions] == ["escalate"]
    action = plan.actions[0]
    assert action.add_label == "needs-human"
    assert "impl-judge" in (action.comment or "")
    assert plan.tracker["pr-782"]["cooldown_until"] is not None


def test_empty_input_is_empty_plan() -> None:
    assert _plan([]).actions == ()


def test_order_preserved_and_deterministic() -> None:
    prs = [
        _pr(3, "bot/impl-3", present=["build-and-push"]),
        _pr(1, "bot/impl-1", present=["build-and-push"]),
        _pr(2, "bot/impl-2", present=["build-and-push"]),
    ]
    first = _plan(prs)
    second = _plan(prs)
    assert [a.number for a in first.actions] == [3, 1, 2]
    assert [a.number for a in first.actions] == [a.number for a in second.actions]
