"""U4 — conflict-heal orchestrator (run.py): planner → rebase → escalate.

Loads the script module by path (it lives under company/scripts/, not the
package) and drives the loop with fakes for gh listing, the rebase script, and
gh mutations — zero real subprocess calls.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_PY = REPO_ROOT / "company" / "scripts" / "conflict-heal" / "run.py"

spec = importlib.util.spec_from_file_location("conflict_heal_run", RUN_PY)
assert spec and spec.loader
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

NOW = "2026-06-21T12:00:00Z"
REPO = "atvirokodosprendimai/wgmesh"


class FakeGh:
    """Records read-only gh list calls; returns a canned PR list."""

    def __init__(self, prs):
        self._prs = prs
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(list(args))
        return json.dumps(self._prs)


class FakeRebase:
    """Returns a scripted OUTCOME per call; records (repo, number, branch)."""

    def __init__(self, outcome):
        self._outcome = outcome
        self.calls: list[tuple] = []

    def __call__(self, repo, number, branch):
        self.calls.append((repo, number, branch))
        return f"OUTCOME={self._outcome} REASON=test"


class FakeMutate:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(list(args))


def _pr(number, head, mergeable):
    return {"number": number, "headRefName": head, "mergeable": mergeable}


def _run(prs, state, *, rebase="rebased", dry_run=False):
    gh = FakeGh(prs)
    rb = FakeRebase(rebase)
    mut = FakeMutate()
    new_state = run.run_conflict_heal(
        REPO, state, NOW, dry_run=dry_run, gh_run=gh, rebase_fn=rb, gh_mutate=mut,
    )
    return new_state, gh, rb, mut


def test_conflicting_bot_pr_rebased_resets_tracker_no_escalation() -> None:
    new_state, gh, rb, mut = _run(
        [_pr(7, "bot/impl-7", "CONFLICTING")], {"retry_tracker": {}}, rebase="rebased"
    )

    assert rb.calls == [(REPO, 7, "bot/impl-7")]
    assert new_state["retry_tracker"] == {}  # R5 clean reset
    assert mut.calls == []  # no escalation
    # listing scoped to the target repo (matrix repo isolation)
    assert "--repo" in gh.calls[0] and REPO in gh.calls[0]


def test_rebase_conflict_increments_retries() -> None:
    new_state, _, rb, mut = _run(
        [_pr(7, "bot/impl-7", "CONFLICTING")],
        {"retry_tracker": {"pr-7": {"retries": 1}}},
        rebase="conflict",
    )

    assert rb.calls == [(REPO, 7, "bot/impl-7")]
    assert new_state["retry_tracker"]["pr-7"]["retries"] == 2
    assert mut.calls == []  # not at cap yet — escalation is next cycle


def test_at_cap_escalates_once_without_rebasing() -> None:
    new_state, _, rb, mut = _run(
        [_pr(7, "bot/impl-7", "CONFLICTING")],
        {"retry_tracker": {"pr-7": {"retries": 2}}},
        rebase="rebased",  # should never be called
    )

    assert rb.calls == []  # planner escalated; no rebase attempt
    # exactly one add-label + one comment
    labels = [c for c in mut.calls if "--add-label" in c]
    comments = [c for c in mut.calls if "comment" in c]
    assert len(labels) == 1 and len(comments) == 1
    assert "needs-human" in labels[0]
    assert "cooldown_until" in new_state["retry_tracker"]["pr-7"]


def test_empty_after_rebase_escalates_no_push() -> None:
    new_state, _, rb, mut = _run(
        [_pr(7, "bot/impl-7", "CONFLICTING")], {"retry_tracker": {}}, rebase="empty"
    )

    assert rb.calls == [(REPO, 7, "bot/impl-7")]  # rebase ran, returned empty
    labels = [c for c in mut.calls if "--add-label" in c]
    assert len(labels) == 1 and "needs-human" in labels[0]
    assert "cooldown_until" in new_state["retry_tracker"]["pr-7"]


def test_dry_run_makes_zero_mutations_and_no_rebase() -> None:
    new_state, _, rb, mut = _run(
        [_pr(7, "bot/impl-7", "CONFLICTING")], {"retry_tracker": {}}, dry_run=True
    )

    assert rb.calls == []
    assert mut.calls == []
    assert new_state["retry_tracker"] == {}


def test_no_conflicting_prs_tracker_unchanged() -> None:
    state = {"retry_tracker": {}}
    new_state, _, rb, mut = _run(
        [_pr(7, "bot/impl-7", "MERGEABLE"), _pr(8, "feature/human-8", "CONFLICTING")],
        state,
    )

    assert rb.calls == [] and mut.calls == []
    # identical file content → no churn commit (idempotency)
    assert json.dumps(new_state, sort_keys=True) == json.dumps(state, sort_keys=True)


def test_normalize_mergeable_unknown_to_none() -> None:
    assert run.normalize_mergeable("UNKNOWN") is None
    assert run.normalize_mergeable("CONFLICTING") == "CONFLICTING"
    assert run.normalize_mergeable("MERGEABLE") == "MERGEABLE"
    assert run.normalize_mergeable(None) is None


def test_parse_outcome() -> None:
    assert run.parse_outcome("OUTCOME=rebased REASON=clean") == "rebased"
    assert run.parse_outcome("OUTCOME=conflict REASON=rebase-conflict") == "conflict"
    assert run.parse_outcome("garbage") == "unknown"
