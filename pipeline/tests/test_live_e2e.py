"""End-to-end live-path proof (mocked): the full loop owns through merge.

Drives the poller through every stage in PIPELINE_MODE=live and asserts the
terminal behaviour: a low-risk issue gets its impl PR created, has auto-merge
ENABLED (U4 — the box never self-merges), then completes to a recorded 'merged'
score once the PR actually merges; a high-risk issue escalates to needs-human
with no merge and an 'escalated' score. No real network/goose/LangSmith.
"""

from __future__ import annotations

import asyncio

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
        # create_pr returns a PR number (+ node_id for the auto-merge mutation)
        if url.endswith("/pulls"):
            return _Response({"number": 4242, "node_id": "PR_4242"})
        # U4: enable_auto_merge issues a GraphQL mutation — it succeeds.
        if method == "POST" and url.endswith("/graphql"):
            return _Response(
                {"data": {"enablePullRequestAutoMerge": {"pullRequest": {}}}}
            )
        # get_pr: the PR carries node_id (for enabling auto-merge) and, once
        # auto-merge has fired (impl-judge + build + status green), reports as
        # merged so the awaiting_merge handler completes it to terminal.
        if method == "GET" and "/pulls/" in url:
            return _Response(
                {
                    "number": 4242,
                    "node_id": "PR_4242",
                    "state": "closed",
                    "merged": True,
                    "user": {"login": "author-bot"},
                    "head": {"sha": "abc"},
                }
            )
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
    for _ in range(max_ticks):
        asyncio.run(p.tick())
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
    # U4: the box ENABLES auto-merge (GraphQL) and never calls the REST /merge
    # endpoint itself; the forge merges the PR once the impl-judge check passes.
    assert any(c["method"] == "POST" and c["url"].endswith("/graphql") for c in session.calls)
    assert not any(c["url"].endswith("/4242/merge") for c in session.calls)
    # The terminal merge is scored 'merged' (auto_merged=1) only on the REAL
    # merge — not at the reviewed->awaiting_merge transition.
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
    # no merge AND no auto-merge enable for a high-risk diff
    assert not any(c["url"].endswith("/merge") for c in session.calls)
    assert not any(c["url"].endswith("/graphql") for c in session.calls)
    # needs-human label applied
    assert any(c["kwargs"].get("json") == {"labels": ["needs-human"]} for c in session.calls)
    assert rec.calls[-1]["outcome"] == "escalated"
    # escalated for the RIGHT reason: the crypto PATH is high-risk (not a
    # coincidental content match) — pins the high-risk-path contract.
    assert rec.calls[-1]["scores"]["risk_tier"] == "high"
    init_scoring(Config(target_repo="r", mode="live", max_files=3))


class _EnableFailSession(_Session):
    def request(self, method, url, **kwargs):
        if method == "POST" and url.endswith("/graphql"):
            self.calls.append({"method": method, "url": url, "kwargs": kwargs})
            raise RuntimeError("502 from GitHub graphql endpoint")
        return super().request(method, url, **kwargs)


def test_live_enable_automerge_failure_leaves_issue_retriable_not_phantom_merged(tmp_path) -> None:
    # If enabling auto-merge fails AFTER the gate decides merge, the issue must
    # NOT be left terminal 'merged' (nor parked in awaiting_merge) with nothing
    # actually enabled. It stays at 'reviewed' (retriable), never silently dropped.
    init_scoring(Config(target_repo="r", mode="live", max_files=3))
    session = _EnableFailSession()
    p = _live_poller(tmp_path, _LowRiskGraph(), session)
    p.store.upsert_issue(584, "Add Polar CTAs")

    issue = _drive_to_terminal(p, 584)

    assert issue.stage != "merged"  # no phantom merge
    assert issue.stage != "awaiting_merge"  # nothing was enabled to await
    # the enable was attempted (and failed)
    assert any(c["url"].endswith("/graphql") for c in session.calls)
