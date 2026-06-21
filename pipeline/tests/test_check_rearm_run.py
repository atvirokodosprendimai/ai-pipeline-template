"""U4 — check-rearm orchestrator (run.py): planner → enable-auto-merge + re-arm
→ escalate.

Loads the script module by path (it lives under company/scripts/, not the
package) and drives the loop with fakes for gh listing, auto-merge enabling, the
re-arm script, and gh mutations — zero real subprocess calls.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_PY = REPO_ROOT / "company" / "scripts" / "check-rearm" / "run.py"

spec = importlib.util.spec_from_file_location("check_rearm_run", RUN_PY)
assert spec and spec.loader
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

NOW = "2026-06-21T12:00:00Z"
REPO = "atvirokodosprendimai/wgmesh"


class FakeGh:
    """Records read-only gh list calls; returns a canned PR list (gh --json)."""

    def __init__(self, prs):
        self._prs = prs
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(list(args))
        return json.dumps(self._prs)


class CallLog:
    """Shared ordered log so we can assert enable-auto-merge precedes re-arm."""

    def __init__(self):
        self.events: list[tuple] = []


class FakeEnable:
    def __init__(self, log, *, raises=False):
        self._log = log
        self._raises = raises
        self.calls: list[tuple] = []

    def __call__(self, repo, number):
        self.calls.append((repo, number))
        self._log.events.append(("enable", repo, number))
        if self._raises:
            raise RuntimeError("auto-merge disabled on repo")


class FakeRearm:
    def __init__(self, log, outcome):
        self._log = log
        self._outcome = outcome
        self.calls: list[tuple] = []

    def __call__(self, repo, number, branch):
        self.calls.append((repo, number, branch))
        self._log.events.append(("rearm", repo, number))
        return f"OUTCOME={self._outcome} REASON=test"


class FakeMutate:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(list(args))


def _pr(number, head, *, title="fix: Issue #1 - thing", mergeable="MERGEABLE",
        is_draft=False, rollup=None):
    return {
        "number": number,
        "headRefName": head,
        "title": title,
        "isDraft": is_draft,
        "mergeable": mergeable,
        "statusCheckRollup": rollup if rollup is not None
        else [{"name": "build-and-push"}, {"name": "status-check"}],
    }


def _run(prs, state, *, outcome="rearmed", dry_run=False, enable_raises=False):
    log = CallLog()
    gh = FakeGh(prs)
    enable = FakeEnable(log, raises=enable_raises)
    rb = FakeRearm(log, outcome)
    mut = FakeMutate()
    new_state = run.run_check_rearm(
        REPO, state, NOW, dry_run=dry_run,
        gh_run=gh, enable_automerge_fn=enable, rearm_fn=rb, gh_mutate=mut,
    )
    return new_state, log, gh, enable, rb, mut


def test_eligible_pr_enables_automerge_then_rearms() -> None:
    new_state, log, gh, enable, rb, mut = _run(
        [_pr(782, "bot/impl-782")], {"retry_tracker": {}}
    )

    assert enable.calls == [(REPO, 782)]
    assert rb.calls == [(REPO, 782, "bot/impl-782")]
    # KTD2: enable auto-merge BEFORE the re-arm push.
    assert log.events == [("enable", REPO, 782), ("rearm", REPO, 782)]
    assert mut.calls == []  # no escalation
    # listing scoped to the target repo and requests the rollup
    assert "--repo" in gh.calls[0] and REPO in gh.calls[0]
    assert any("statusCheckRollup" in tok for tok in gh.calls[0])
    # re-arm recorded with a recheck cooldown so the next tick won't thrash
    entry = new_state["retry_tracker"]["pr-782"]
    assert entry["retries"] == 1 and entry["cooldown_until"] > NOW


def test_check_already_present_skips_everything() -> None:
    new_state, _, _, enable, rb, mut = _run(
        [_pr(782, "bot/impl-782", rollup=[{"name": "impl-judge"}, {"name": "build-and-push"}])],
        {"retry_tracker": {}},
    )
    assert enable.calls == [] and rb.calls == [] and mut.calls == []
    assert new_state["retry_tracker"] == {}


def test_enable_failure_does_not_abort_rearm() -> None:
    # OQ2: a repo with auto-merge disabled makes enable raise — we still re-arm.
    new_state, log, _, enable, rb, _ = _run(
        [_pr(782, "bot/impl-782")], {"retry_tracker": {}}, enable_raises=True
    )
    assert enable.calls == [(REPO, 782)]
    assert rb.calls == [(REPO, 782, "bot/impl-782")]
    assert new_state["retry_tracker"]["pr-782"]["retries"] == 1


def test_rearm_error_increments_toward_cap() -> None:
    new_state, _, _, _, rb, mut = _run(
        [_pr(782, "bot/impl-782")],
        {"retry_tracker": {"pr-782": {"retries": 1, "cooldown_until": "2026-06-21T06:00:00Z"}}},
        outcome="error",
    )
    assert rb.calls == [(REPO, 782, "bot/impl-782")]
    assert new_state["retry_tracker"]["pr-782"]["retries"] == 2
    assert mut.calls == []  # escalation is next cycle, by the planner


def test_at_cap_escalates_without_enabling_or_rearming() -> None:
    new_state, _, _, enable, rb, mut = _run(
        [_pr(782, "bot/impl-782")],
        {"retry_tracker": {"pr-782": {"retries": 2}}},
    )
    assert enable.calls == [] and rb.calls == []  # planner escalated
    labels = [c for c in mut.calls if "--add-label" in c]
    comments = [c for c in mut.calls if "comment" in c]
    assert len(labels) == 1 and "needs-human" in labels[0]
    assert len(comments) == 1
    assert "cooldown_until" in new_state["retry_tracker"]["pr-782"]


def test_dry_run_makes_zero_mutations() -> None:
    new_state, _, _, enable, rb, mut = _run(
        [_pr(782, "bot/impl-782")], {"retry_tracker": {}}, dry_run=True
    )
    assert enable.calls == [] and rb.calls == [] and mut.calls == []
    assert new_state["retry_tracker"] == {}


def test_idempotent_no_change_no_churn() -> None:
    # An armed PR (judge present) → planner skips → state identical (no churn commit).
    state = {"retry_tracker": {}}
    new_state, *_ = _run(
        [_pr(782, "bot/impl-782", rollup=[{"name": "impl-judge"}])], state
    )
    assert json.dumps(new_state, sort_keys=True) == json.dumps(state, sort_keys=True)


def test_present_contexts_parses_names_and_status_contexts() -> None:
    rollup = [
        {"name": "impl-judge"},          # check run
        {"context": "ci/legacy"},        # commit status
        {"unrelated": "x"},              # ignored
    ]
    assert run.present_contexts(rollup) == frozenset({"impl-judge", "ci/legacy"})
    assert run.present_contexts(None) == frozenset()


def test_normalize_mergeable() -> None:
    assert run.normalize_mergeable("UNKNOWN") is None
    assert run.normalize_mergeable("MERGEABLE") == "MERGEABLE"
    assert run.normalize_mergeable("CONFLICTING") == "CONFLICTING"
    assert run.normalize_mergeable(None) is None


def test_parse_outcome() -> None:
    assert run.parse_outcome("OUTCOME=rearmed REASON=empty-commit-pushed") == "rearmed"
    assert run.parse_outcome("OUTCOME=error REASON=push-failed") == "error"
    assert run.parse_outcome("garbage") == "unknown"
