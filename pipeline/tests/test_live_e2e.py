"""End-to-end live-path proof (mocked): the full loop owns through merge.

Drives the poller through every stage in PIPELINE_MODE=live and asserts the
terminal behaviour: a low-risk issue gets its impl PR created AND merged with a
recorded 'merged' score; a high-risk issue escalates to needs-human with no
merge and an 'escalated' score. No real network/goose/LangSmith.
"""

from __future__ import annotations

import asyncio

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient
from wgmesh_pipeline.poller import Poller
from wgmesh_pipeline.scoring import init_scoring
from wgmesh_pipeline.state.store import StateStore


class _Response:
    def __init__(self, data):
        self._data = data
        self.text = "json"

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._data


class _Session:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        # create_pr returns a PR number; everything else returns ok
        if url.endswith("/pulls"):
            return _Response({"number": 4242})
        return _Response({"ok": True})


class _RecordingClient(GitHubClient):
    def list_open_issues(self):
        return []

    # bypass real git/sanitise subprocess work for the e2e mock
    def push_branch(self, clone_path, branch, *, spec_pr=False):
        return self._write("push_branch", {"branch": branch}, spec_pr=spec_pr)


class _LowRiskGraph:
    def __init__(self):
        self.calls = []

    def triage(self, state):
        self.calls.append("triage")
        return {**state, "classification": "fix"}

    def spec(self, state):
        self.calls.append("spec")
        return {**state, "spec_path": "specs/issue.md"}

    def spec_pr(self, state):
        self.calls.append("spec_pr")
        return {**state, "spec_pr": 11}

    def implement(self, state):
        self.calls.append("implement")
        return {**state, "diff": "+docs\n", "changed_files": ["docs/readme.md"], "impl_pr": 4242}

    def review(self, state):
        self.calls.append("review")
        return {**state, "tests_passed": True, "sanitise_ok": True, "review_findings": []}


class _HighRiskGraph(_LowRiskGraph):
    def implement(self, state):
        self.calls.append("implement")
        return {**state, "diff": "+secret\n", "changed_files": ["internal/crypto/key.go"], "impl_pr": 4242}


class _Recorder:
    def __init__(self):
        self.calls = []

    def record(self, *, issue, outcome, scores, tags, trace_id=None):
        self.calls.append({"issue": issue, "outcome": outcome, "scores": scores, "trace_id": trace_id})


def _drive_to_terminal(p: Poller, issue_number: int, max_ticks: int = 12):
    last = None
    for _ in range(max_ticks):
        last = asyncio.run(p.tick())
        rec = p.store.get_issue(issue_number)
        if rec.stage in {"merged", "escalated", "failed"}:
            return rec
    return p.store.get_issue(issue_number)


def _live_poller(tmp_path, graph, session):
    cfg = Config(target_repo="atvirokodosprendimai/wgmesh", mode="live", max_files=3)
    store = StateStore(tmp_path / "state.db")
    client = _RecordingClient(cfg, session=session)
    return Poller(config=cfg, store=store, client=client, graph=graph)


def test_live_low_risk_issue_merges_and_scores(tmp_path) -> None:
    rec = _Recorder()
    init_scoring(Config(target_repo="r", mode="live", max_files=3), scorer=rec)
    session = _Session()
    p = _live_poller(tmp_path, _LowRiskGraph(), session)
    p.store.upsert_issue(584, "Add Polar CTAs")

    issue = _drive_to_terminal(p, 584)

    assert issue.stage == "merged"
    # the real impl PR (4242) was merged, not 0
    merges = [c for c in session.calls if c["url"].endswith("/4242/merge")]
    assert len(merges) == 1
    assert rec.calls[-1]["outcome"] == "merged"
    assert rec.calls[-1]["scores"]["auto_merged"] == 1
    init_scoring(Config(target_repo="r", mode="live", max_files=3))  # reset module scorer


def test_live_high_risk_issue_escalates_no_merge(tmp_path) -> None:
    rec = _Recorder()
    init_scoring(Config(target_repo="r", mode="live", max_files=3), scorer=rec)
    session = _Session()
    p = _live_poller(tmp_path, _HighRiskGraph(), session)
    p.store.upsert_issue(540, "Key rotation bug")

    issue = _drive_to_terminal(p, 540)

    assert issue.stage == "escalated"
    # no merge call for a high-risk diff
    assert not any(c["url"].endswith("/merge") for c in session.calls)
    # needs-human label applied
    assert any(c["kwargs"].get("json") == {"labels": ["needs-human"]} for c in session.calls)
    assert rec.calls[-1]["outcome"] == "escalated"
    # escalated for the RIGHT reason: the crypto PATH is high-risk (not a
    # coincidental content match) — pins the high-risk-path contract.
    assert rec.calls[-1]["scores"]["risk_tier"] == "high"
    init_scoring(Config(target_repo="r", mode="live", max_files=3))


class _MergeFailSession(_Session):
    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        if url.endswith("/pulls"):
            return _Response({"number": 4242})
        if url.endswith("/merge"):
            raise RuntimeError("502 from GitHub merge endpoint")
        return _Response({"ok": True})


def test_live_merge_failure_leaves_issue_retriable_not_phantom_merged(tmp_path) -> None:
    # If the merge network call fails AFTER the gate decides merge, the issue
    # must NOT be left terminal 'merged' with the PR unmerged. It stays at
    # 'reviewed' (retriable), never silently dropped.
    init_scoring(Config(target_repo="r", mode="live", max_files=3))
    session = _MergeFailSession()
    p = _live_poller(tmp_path, _LowRiskGraph(), session)
    p.store.upsert_issue(584, "Add Polar CTAs")

    issue = _drive_to_terminal(p, 584)

    assert issue.stage != "merged"  # no phantom merge
    # the merge was attempted (and failed), issue is bumped/retriable, not terminal-merged
    assert any(c["url"].endswith("/4242/merge") for c in session.calls)
