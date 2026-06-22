"""U2 — merge-lane-heal box module: run_merge_lane_heal.

Pure/fake-driven: a FakeForge exposes all duck-typed forge methods returning
canned data; a FakeRebase records calls and returns scripted outcomes.  Zero
real network calls or subprocess invocations.

Covers:
  - shadow (live=False) plans actions but executes nothing
  - live: CONFLICTING bot PR → rebase called (Pass A)
  - live: MERGEABLE+behind+failing check bot PR → rebase called (Pass C — the
    failure may be a stale tree; rebase to re-run checks against fixed main)
  - live: MERGEABLE+behind+green bot PR → NOT rebased (thrash guard)
  - live: MERGEABLE+current bot PR → nothing
  - cross-pass double-action guard (Pass A actioned PR skipped by Pass C)
  - cross-pass ordering (A before C in combined actions tuple)
  - rebased outcome resets tracker entry (R5)
  - empty outcome escalates (add_label + comment called)
  - escalate action adds needs-human + comment
  - non-bot PRs never touched
"""

from __future__ import annotations

from typing import Any

from wgmesh_pipeline.selfheal.merge_lane import run_merge_lane_heal
from wgmesh_pipeline.selfheal.models import (
    HEAL_KIND_CHECK_REARM,
    HEAL_KIND_CONFLICT_REBASE,
    HEAL_KIND_STALE_BASE_REBASE,
)

NOW = "2026-06-21T12:00:00Z"


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeForge:
    """Duck-typed forge exposing only the methods merge_lane uses."""

    def __init__(
        self,
        prs: list[dict[str, Any]],
        *,
        mergeables: dict[int, str | None] | None = None,
        behind_by: dict[str, int] | None = None,
        failing: dict[int, bool] | None = None,
        target_repo: str = "org/repo",
    ) -> None:
        # prs: list of {number, headRefName} (list_open_pull_requests output)
        self._prs = prs
        self._mergeables: dict[int, str | None] = mergeables or {}
        self._behind_by: dict[str, int] = behind_by or {}
        self._failing: dict[int, bool] = failing or {}
        # Expose config-like object so merge_lane can read target_repo
        self.config = type("cfg", (), {"target_repo": target_repo})()
        # Mutation records
        self.labels_added: list[tuple[int, str]] = []
        self.comments: list[tuple[int, str]] = []
        self.auto_merges: list[int] = []

    def list_open_pull_requests(self) -> list[dict[str, Any]]:
        return list(self._prs)

    def get_pr_mergeable(self, number: int) -> str | None:
        return self._mergeables.get(number)

    def compare_behind_by(self, head_branch: str, **_: Any) -> int:
        return self._behind_by.get(head_branch, 0)

    def pr_has_failing_check(self, number: int) -> bool:
        return self._failing.get(number, False)

    def add_label(self, issue_number: int, label: str, **_: Any) -> None:
        self.labels_added.append((issue_number, label))

    def comment(self, issue_number: int, body: str) -> None:
        self.comments.append((issue_number, body))

    def enable_auto_merge(self, pr_number: int, **_: Any) -> None:
        self.auto_merges.append(pr_number)


class FakeRebase:
    """Records (repo, number, branch) calls; returns scripted OUTCOME lines."""

    def __init__(self, outcome: str = "rebased") -> None:
        self._outcome = outcome
        self.calls: list[tuple[str, int, str]] = []

    def __call__(self, repo: str, number: int, branch: str) -> str:
        self.calls.append((repo, number, branch))
        return f"OUTCOME={self._outcome} REASON=test"


# ── Helper builders ────────────────────────────────────────────────────────────

def _pr(number: int, head: str) -> dict[str, Any]:
    return {"number": number, "headRefName": head}


def _run(
    prs: list[dict[str, Any]],
    *,
    mergeables: dict[int, str | None] | None = None,
    behind_by: dict[str, int] | None = None,
    failing: dict[int, bool] | None = None,
    state: dict[str, Any] | None = None,
    live: bool = True,
    rebase_outcome: str = "rebased",
) -> tuple["MergeLaneHealRun", FakeForge, FakeRebase]:  # type: ignore[name-defined]
    forge = FakeForge(prs, mergeables=mergeables, behind_by=behind_by, failing=failing)
    rb = FakeRebase(rebase_outcome)
    result = run_merge_lane_heal(
        forge, state or {}, NOW, live=live, rebase_fn=rb,
    )
    return result, forge, rb


# ── Shadow tests ───────────────────────────────────────────────────────────────

def test_shadow_plans_actions_but_mutates_nothing() -> None:
    """Shadow mode returns planned actions but calls no forge mutations."""
    result, forge, rb = _run(
        [_pr(7, "bot/impl-7")],
        mergeables={7: "CONFLICTING"},
        live=False,
    )
    # Planned CONFLICTING → should have a conflict_rebase action
    assert any(a.kind == HEAL_KIND_CONFLICT_REBASE for a in result.actions)
    # No forge mutations
    assert forge.labels_added == []
    assert forge.comments == []
    assert rb.calls == []
    assert result.dry_run is True
    assert result.executed == 0


# ── Non-bot PR guard ──────────────────────────────────────────────────────────

def test_human_pr_never_touched() -> None:
    """Human PRs (no bot/ prefix) are ignored in all passes."""
    result, forge, rb = _run(
        [_pr(10, "fix/human-fix"), _pr(11, "feature/foo")],
        mergeables={10: "CONFLICTING", 11: "MERGEABLE"},
        behind_by={"feature/foo": 5},
        live=True,
    )
    assert result.actions == ()
    assert rb.calls == []
    assert forge.labels_added == []


# ── Pass A: conflict-rebase ───────────────────────────────────────────────────

def test_conflicting_bot_pr_rebase_called() -> None:
    """A CONFLICTING bot PR causes rebase_fn to be called."""
    result, forge, rb = _run(
        [_pr(7, "bot/impl-7")],
        mergeables={7: "CONFLICTING"},
        live=True,
    )
    assert len(rb.calls) == 1
    assert rb.calls[0][1] == 7  # PR number
    assert result.executed == 1


def test_rebased_outcome_resets_tracker_entry() -> None:
    """A 'rebased' outcome clears the tracker entry for the PR (R5)."""
    state = {"retry_tracker": {"pr-7": {"retries": 1, "last_retry": NOW}}}
    result, _, _ = _run(
        [_pr(7, "bot/impl-7")],
        mergeables={7: "CONFLICTING"},
        state=state,
        live=True,
        rebase_outcome="rebased",
    )
    assert "pr-7" not in result.state["retry_tracker"]


def test_conflict_outcome_increments_retries() -> None:
    """A 'conflict' outcome increments retries in the tracker."""
    result, _, _ = _run(
        [_pr(7, "bot/impl-7")],
        mergeables={7: "CONFLICTING"},
        live=True,
        rebase_outcome="conflict",
    )
    entry = result.state["retry_tracker"]["pr-7"]
    assert entry["retries"] == 1


def test_empty_outcome_escalates() -> None:
    """An 'empty' outcome (already-merged content) adds needs-human label + comment."""
    result, forge, rb = _run(
        [_pr(7, "bot/impl-7")],
        mergeables={7: "CONFLICTING"},
        live=True,
        rebase_outcome="empty",
    )
    assert any(label == "needs-human" for _, label in forge.labels_added)
    assert len(forge.comments) == 1
    assert "7" in forge.comments[0][1] or "main" in forge.comments[0][1]


# ── Pass C: stale-base-rebase ─────────────────────────────────────────────────

def test_mergeable_behind_failing_check_rebased() -> None:
    """A MERGEABLE bot PR behind main WITH a failing check is the stale-base
    candidate — the failure may be a stale tree (since-merged fix), so rebase
    onto main to re-run checks against the fixed tree."""
    result, forge, rb = _run(
        [_pr(8, "bot/impl-8")],
        mergeables={8: "MERGEABLE"},
        behind_by={"bot/impl-8": 3},
        failing={8: True},
        live=True,
    )
    # Pass B won't act (empty title → no "fix: Issue #" prefix). Pass C acts.
    stale_actions = [a for a in result.actions if a.kind == HEAL_KIND_STALE_BASE_REBASE]
    assert len(stale_actions) == 1
    assert stale_actions[0].number == 8


def test_mergeable_behind_green_pr_not_rebased() -> None:
    """Thrash guard: a MERGEABLE bot PR behind main but with NO failing check is
    skipped — a green PR must never be force-pushed (it can merge as-is)."""
    result, forge, rb = _run(
        [_pr(8, "bot/impl-8")],
        mergeables={8: "MERGEABLE"},
        behind_by={"bot/impl-8": 3},
        failing={8: False},
        live=True,
    )
    stale_actions = [a for a in result.actions if a.kind == HEAL_KIND_STALE_BASE_REBASE]
    assert len(stale_actions) == 0
    assert rb.calls == []


def test_mergeable_current_pr_not_touched() -> None:
    """A MERGEABLE bot PR that is up-to-date (behind_by=0) is not rebased."""
    result, forge, rb = _run(
        [_pr(8, "bot/impl-8")],
        mergeables={8: "MERGEABLE"},
        behind_by={"bot/impl-8": 0},
        failing={8: False},
        live=True,
    )
    assert result.actions == ()
    assert rb.calls == []


# ── Double-action guard (cross-pass) ──────────────────────────────────────────

def test_conflicting_pr_not_double_actioned_by_pass_c() -> None:
    """A PR actioned by Pass A (conflict-rebase) is NOT also actioned by Pass C."""
    # PR 7 is CONFLICTING → Pass A will rebase it.
    # From Pass C's perspective, a CONFLICTING PR has mergeable != MERGEABLE, so
    # it won't appear in prs_for_stale anyway — but we add it to behind_by to
    # confirm the guard is in place even if the planner inputs were artificially
    # constructed to include it.
    result, forge, rb = _run(
        [_pr(7, "bot/impl-7")],
        mergeables={7: "CONFLICTING"},
        behind_by={"bot/impl-7": 5},
        failing={7: False},
        live=True,
    )
    stale_actions = [a for a in result.actions if a.kind == HEAL_KIND_STALE_BASE_REBASE]
    assert len(stale_actions) == 0, (
        "CONFLICTING PR should not be double-actioned by stale-base pass"
    )
    conflict_actions = [a for a in result.actions if a.kind == HEAL_KIND_CONFLICT_REBASE]
    assert len(conflict_actions) == 1


def test_pass_a_action_appears_before_pass_c_in_combined() -> None:
    """When both Pass A and Pass C have candidates, Pass A actions precede Pass C."""
    result, forge, rb = _run(
        [_pr(7, "bot/impl-7"), _pr(8, "bot/impl-8")],
        mergeables={7: "CONFLICTING", 8: "MERGEABLE"},
        behind_by={"bot/impl-8": 3},
        failing={8: True},  # behind + failing → stale-base candidate
        live=False,  # shadow: just check action order
    )
    kinds = [a.kind for a in result.actions]
    assert HEAL_KIND_CONFLICT_REBASE in kinds
    assert HEAL_KIND_STALE_BASE_REBASE in kinds
    a_idx = next(i for i, k in enumerate(kinds) if k == HEAL_KIND_CONFLICT_REBASE)
    c_idx = next(i for i, k in enumerate(kinds) if k == HEAL_KIND_STALE_BASE_REBASE)
    assert a_idx < c_idx, "Pass A actions must appear before Pass C actions"


# ── Escalate action ──────────────────────────────────────────────────────────

def test_escalate_action_adds_needs_human_and_comment() -> None:
    """An escalate action adds the needs-human label and a comment on the PR."""
    # Exhaust retry cap so the planner escalates
    state = {"retry_tracker": {"pr-7": {"retries": 2, "last_retry": NOW}}}
    result, forge, rb = _run(
        [_pr(7, "bot/impl-7")],
        mergeables={7: "CONFLICTING"},
        state=state,
        live=True,
    )
    # No rebase should have been attempted (escalate, not act)
    assert rb.calls == []
    assert any(label == "needs-human" for _, label in forge.labels_added)
    assert len(forge.comments) >= 1
