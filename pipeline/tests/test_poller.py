from __future__ import annotations

import asyncio

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.box_ci import BoxCiResult
from wgmesh_pipeline.github.client import GitHubClient
from wgmesh_pipeline.graph.build import build_graph
from wgmesh_pipeline.poller import Poller
from wgmesh_pipeline.scoring import init_scoring
from wgmesh_pipeline.state.store import StateStore


class EmptyClient(GitHubClient):
    def list_open_issues(self):
        return []


class Response:
    def __init__(self, data):
        self._data = data
        self.text = "json"

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._data


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self.response


class Graph:
    def __init__(self):
        self.calls: list[str] = []

    def triage(self, state):
        self.calls.append("triage")
        return {**state, "classification": "fix"}

    def spec(self, state):
        self.calls.append("spec")
        return {**state, "spec_path": "specs/issue.md"}

    def spec_pr(self, state):
        self.calls.append("spec_pr")
        return {**state, "spec_pr": 99}

    def implement(self, state):
        self.calls.append("implement")
        return {**state, "diff": "+diff\n", "changed_files": ["docs/readme.md"]}

    def review(self, state):
        self.calls.append("review")
        return {
            **state,
            "tests_passed": True,
            "sanitise_ok": True,
            "review_findings": [],
        }


class RecordingScorer:
    def __init__(self):
        self.calls: list[dict] = []

    def record(self, *, issue, outcome, scores, tags, trace_id=None):
        self.calls.append(
            {
                "issue": issue,
                "outcome": outcome,
                "scores": scores,
                "tags": tags,
                "trace_id": trace_id,
            }
        )


@pytest.fixture
def cfg() -> Config:
    return Config(target_repo="atvirokodosprendimai/wgmesh", mode="shadow", max_files=3)


def poller(tmp_path, cfg: Config, graph=None):
    store = StateStore(tmp_path / "state.db")
    client = EmptyClient(cfg)
    return Poller(config=cfg, store=store, client=client, graph=graph or Graph())


def test_tick_advances_queued_issue_to_triaged_and_records_run(
    tmp_path, cfg: Config
) -> None:
    p = poller(tmp_path, cfg)
    p.store.upsert_issue(1, "Fix bug")

    result = asyncio.run(p.tick())

    assert result is not None
    assert result.stage == "triaged"
    assert p.store.get_issue(1).classification == "fix"
    assert p.store.list_runs()[0]["node"] == "queued"
    assert p.store.list_runs()[0]["outcome"] == "ok"


def test_spec_only_wont_do_issue_escalates_and_is_not_reclaimed(
    tmp_path, cfg: Config
) -> None:
    class WontDoGraph(Graph):
        def triage(self, state):
            self.calls.append("triage")
            return {**state, "classification": "wont-do"}

    class SpecOnlyClient(GitHubClient):
        def list_open_issues(self):
            return []

        def get_issue(self, number: int):
            if number == 1:
                from wgmesh_pipeline.github.client import GitHubIssue

                return GitHubIssue(
                    number=1, title="Do not build", labels=(), state="open"
                )
            return None

    spec_only = Config(
        target_repo=cfg.target_repo, mode="spec-only", max_files=cfg.max_files
    )
    session = Session(Response({"ok": True}))
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(1, "Do not build")
    graph = WontDoGraph()
    p = Poller(
        config=spec_only,
        store=store,
        client=SpecOnlyClient(spec_only, session=session),
        graph=graph,
    )

    result = asyncio.run(p.tick())
    second = asyncio.run(p.tick())

    issue = store.get_issue(1)
    assert result is not None
    assert result.stage == "escalated"
    assert issue.stage == "escalated"
    assert issue.attempts == 0
    assert issue.last_error is None
    assert second is None
    assert graph.calls == ["triage"]
    assert len(session.calls) == 1
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["kwargs"]["json"] == {"labels": ["needs-human"]}


def test_live_mode_resumes_spec_opened_issue(tmp_path, cfg: Config) -> None:
    live = Config(target_repo=cfg.target_repo, mode="live", max_files=cfg.max_files)
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(12, "Implement approved spec", stage="spec_opened", spec_pr=99)
    p = Poller(config=live, store=store, client=EmptyClient(live), graph=Graph())

    result = asyncio.run(p.tick())

    assert result is not None
    assert result.stage == "spec_ready"
    assert store.get_issue(12).stage == "spec_ready"
    assert store.list_runs()[0]["node"] == "spec_opened"
    assert store.list_runs()[0]["outcome"] == "ok"


def test_spec_only_mode_never_claims_spec_opened(tmp_path, cfg: Config) -> None:
    spec_only = Config(
        target_repo=cfg.target_repo, mode="spec-only", max_files=cfg.max_files
    )
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(12, "Spec already opened", stage="spec_opened", spec_pr=99)
    p = Poller(
        config=spec_only, store=store, client=EmptyClient(spec_only), graph=Graph()
    )

    result = asyncio.run(p.tick())

    assert result is None
    assert store.get_issue(12).stage == "spec_opened"
    assert store.list_runs() == []


def test_tick_no_actionable_issue_is_noop(tmp_path, cfg: Config) -> None:
    p = poller(tmp_path, cfg)

    result = asyncio.run(p.tick())

    assert result is None
    assert p.store.list_runs() == []


def test_graph_exception_bumps_attempt_and_loop_continues(
    tmp_path, cfg: Config
) -> None:
    class FailingGraph(Graph):
        def triage(self, state):
            raise RuntimeError("bad issue")

    p = poller(tmp_path, cfg, FailingGraph())
    p.store.upsert_issue(1, "Fix bug")

    result = asyncio.run(p.tick())

    assert result is None
    issue = p.store.get_issue(1)
    assert issue.attempts == 1
    assert issue.last_error == "bad issue"
    assert p.store.list_runs()[0]["outcome"] == "error"


def test_reconcile_exception_does_not_halt_tick(
    tmp_path, cfg: Config, monkeypatch
) -> None:
    p = poller(tmp_path, cfg)
    p.store.upsert_issue(1, "Fix bug")

    def fail_reconcile(client, store, **kwargs):
        raise RuntimeError("github unavailable")

    monkeypatch.setattr("wgmesh_pipeline.poller.reconcile_issues", fail_reconcile)

    result = asyncio.run(p.tick())

    assert result is None
    assert p.last_reconcile_error == "github unavailable"
    assert p.store.get_issue(1).stage == "queued"


def test_reconcile_exception_records_failed_score_with_stage_and_truncated_error(
    tmp_path, cfg: Config, monkeypatch
) -> None:
    scorer = RecordingScorer()
    init_scoring(cfg, scorer=scorer)
    p = poller(tmp_path, cfg)
    p.store.upsert_issue(1, "Fix bug")

    def fail_reconcile(client, store, **kwargs):
        raise RuntimeError("x" * 250)

    monkeypatch.setattr("wgmesh_pipeline.poller.reconcile_issues", fail_reconcile)

    result = asyncio.run(p.tick())

    assert result is None
    assert scorer.calls[0]["outcome"] == "failed"
    assert scorer.calls[0]["tags"]["stage"] == "reconcile"
    assert scorer.calls[0]["tags"]["node"] == "reconcile"
    assert len(scorer.calls[0]["tags"]["error"]) == 200


def test_advance_exception_records_failed_score_with_node_tag(
    tmp_path, cfg: Config
) -> None:
    class FailingGraph(Graph):
        def triage(self, state):
            raise RuntimeError("bad issue")

    scorer = RecordingScorer()
    init_scoring(cfg, scorer=scorer)
    p = poller(tmp_path, cfg, FailingGraph())
    p.store.upsert_issue(1, "Fix bug")

    result = asyncio.run(p.tick())

    assert result is None
    assert scorer.calls[0]["outcome"] == "failed"
    assert scorer.calls[0]["tags"]["node"] == "queued"
    assert scorer.calls[0]["tags"]["stage"] == "queued"
    assert scorer.calls[0]["tags"]["error"] == "bad issue"


def test_success_tick_does_not_record_failure_score(tmp_path, cfg: Config) -> None:
    scorer = RecordingScorer()
    init_scoring(cfg, scorer=scorer)
    p = poller(tmp_path, cfg)
    p.store.upsert_issue(1, "Fix bug")

    result = asyncio.run(p.tick())

    assert result is not None
    assert [call for call in scorer.calls if call["outcome"] == "failed"] == []


def test_reviewed_issue_not_phantom_merged_when_side_effect_fails(
    tmp_path, cfg: Config
) -> None:
    # U4: the merge-decision side effect is enable_auto_merge (NOT a self-merge).
    # If it fails, the issue must NOT advance to awaiting_merge/merged — it stays
    # at 'reviewed', retriable. No phantom completion.
    class FailingEnableClient(EmptyClient):
        def __init__(self, config):
            super().__init__(config)
            self.enable_calls: list[int] = []

        def enable_auto_merge(self, pr_number: int, *, merge_method: str = "SQUASH"):
            self.enable_calls.append(pr_number)
            raise RuntimeError("enable auto-merge side effect failed")

    live = Config(target_repo=cfg.target_repo, mode="live", max_files=cfg.max_files)
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(2, "Ready", stage="reviewed", impl_pr=321)
    client = FailingEnableClient(live)
    p = Poller(config=live, store=store, client=client, graph=Graph())
    p.scratch[2] = {
        "diff": "+docs\n",
        "changed_files": ["docs/readme.md"],
        "tests_passed": True,
        "sanitise_ok": True,
        "review_findings": [],
        "impl_pr": 321,
    }

    result = asyncio.run(p.tick())

    assert result is None
    assert client.enable_calls == [321]
    assert store.get_issue(2).stage == "reviewed"  # not awaiting_merge, not merged


def test_restart_mid_flight_resumes_persisted_stage_without_double_work(
    tmp_path, cfg: Config
) -> None:
    db_path = tmp_path / "state.db"
    StateStore(db_path).upsert_issue(1, "Already triaged", stage="triaged")
    graph = Graph()
    restarted = Poller(
        config=cfg, store=StateStore(db_path), client=EmptyClient(cfg), graph=graph
    )

    result = asyncio.run(restarted.tick())

    assert result is not None
    assert result.stage == "specced"
    assert graph.calls == ["spec"]


def test_advance_one_stage_injects_goose_runner_and_repo_path(
    tmp_path, cfg: Config
) -> None:
    class InspectingGraph(Graph):
        def __init__(self) -> None:
            super().__init__()
            self.seen_state = None

        def spec(self, state):
            self.calls.append("spec")
            self.seen_state = dict(state)
            return {**state, "spec_path": "specs/issue-17-spec.md"}

    graph = InspectingGraph()
    repo_path = tmp_path / "wgmesh"
    runner = object()

    def box_ci(forge, pr):
        return BoxCiResult(green=True, failures=())

    spec_only = Config(
        target_repo=cfg.target_repo, mode="spec-only", repo_path=str(repo_path)
    )
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(17, "Already triaged", stage="triaged")
    p = Poller(
        config=spec_only,
        store=store,
        client=EmptyClient(spec_only),
        graph=graph,
        goose_runner=runner,
        box_ci=box_ci,
    )

    p._advance_one_stage(store.get_issue(17))

    assert graph.seen_state is not None
    assert graph.seen_state["goose_runner"] is runner
    assert graph.seen_state["repo_path"] == repo_path
    assert graph.seen_state["config"] is spec_only
    assert graph.seen_state["box_ci"] is box_ci


def test_specced_issue_opens_spec_pr_then_stops_in_spec_only(
    tmp_path, cfg: Config
) -> None:
    spec_only = Config(
        target_repo=cfg.target_repo, mode="spec-only", max_files=cfg.max_files
    )
    p = poller(tmp_path, spec_only)
    p.store.upsert_issue(1, "Already specced", stage="specced")

    result = asyncio.run(p.tick())
    second = asyncio.run(p.tick())

    assert result is not None
    assert result.stage == "spec_opened"
    assert second is None
    assert p.store.get_issue(1).spec_pr == 99
    assert p.graph.calls == ["spec_pr"]


def test_spec_opened_terminal_is_scored_in_spec_only(tmp_path, cfg: Config) -> None:
    """spec_opened (spec-only terminal) emits a score so the Langfuse Scores
    view reflects spec-only throughput, not just escalate/error/merge."""
    from wgmesh_pipeline.scoring import init_scoring

    spec_only = Config(
        target_repo=cfg.target_repo, mode="spec-only", max_files=cfg.max_files
    )
    scorer = RecordingScorer()
    init_scoring(spec_only, scorer=scorer)
    try:
        p = poller(tmp_path, spec_only)
        p.store.upsert_issue(1, "Already specced", stage="specced")
        asyncio.run(p.tick())
        outcomes = [c["outcome"] for c in scorer.calls]
        assert "spec_opened" in outcomes
        assert [c for c in scorer.calls if c["outcome"] == "spec_opened"][0][
            "issue"
        ] == 1
    finally:
        init_scoring(Config(target_repo=cfg.target_repo))  # reset module scorer


def test_specced_issue_in_shadow_does_not_open_spec_pr_or_advance(
    tmp_path, cfg: Config
) -> None:
    p = poller(tmp_path, cfg)
    p.store.upsert_issue(1, "Already specced", stage="specced")

    result = asyncio.run(p.tick())

    assert result is not None
    assert result.stage == "specced"
    assert p.store.get_issue(1).stage == "specced"
    assert p.store.get_issue(1).spec_pr is None
    assert p.graph.calls == []


def test_spec_ready_issue_continues_to_implementation(tmp_path, cfg: Config) -> None:
    live = Config(target_repo=cfg.target_repo, mode="live", max_files=cfg.max_files)
    p = poller(tmp_path, live)
    p.store.upsert_issue(1, "Spec PR opened", stage="spec_ready", spec_pr=99)

    result = asyncio.run(p.tick())

    assert result is not None
    assert result.stage == "implemented"
    assert p.graph.calls == ["implement"]


def test_main_graph_shadow_fixture_halts_at_specced_without_writes(
    tmp_path, cfg: Config, monkeypatch
) -> None:
    monkeypatch.setattr(
        "wgmesh_pipeline.graph.nodes.review.run_sanitise", lambda text: True
    )
    client = EmptyClient(cfg)
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(1, "Fix docs")
    p = Poller(config=cfg, store=store, client=client, graph=build_graph(cfg))
    p.scratch[1] = {"verification": {"tests_passed": True}}

    for _ in range(3):
        asyncio.run(p.tick())

    assert store.get_issue(1).stage == "specced"
    assert client.dry_run_records == []


def test_reviewed_merge_enables_automerge_and_parks_awaiting_merge(
    tmp_path, cfg: Config
) -> None:
    """U4: on a merge decision the box ENABLES auto-merge (no self-merge) and
    parks the issue in awaiting_merge — completion to merged happens only on the
    real merge (the awaiting_merge handler), never here."""

    class EnablingClient(EmptyClient):
        def __init__(self, config):
            super().__init__(config)
            self.enabled: list[int] = []
            self.merged_prs: list[int] = []

        def enable_auto_merge(self, pr_number, *, merge_method="SQUASH"):
            self.enabled.append(pr_number)
            return None

        def merge_pr(self, pr_number, *, commit_title=None):
            self.merged_prs.append(pr_number)
            return {"merged": True}

    live = Config(target_repo=cfg.target_repo, mode="live", max_files=cfg.max_files)
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(3, "Ready", stage="reviewed", impl_pr=321)
    client = EnablingClient(live)
    p = Poller(config=live, store=store, client=client, graph=Graph())
    p.scratch[3] = {
        "diff": "+docs\n",
        "changed_files": ["docs/readme.md"],
        "tests_passed": True,
        "sanitise_ok": True,
        "review_findings": [],
        "impl_pr": 321,
    }

    result = asyncio.run(p.tick())

    assert result is not None
    assert store.get_issue(3).stage == "awaiting_merge"
    assert client.enabled == [321]
    assert client.merged_prs == []  # the box does NOT self-merge


class _PrStateClient(EmptyClient):
    """Fake client whose get_pr returns a fixed PR payload; records add_label."""

    def __init__(self, config, pr_payload):
        super().__init__(config)
        self._pr = pr_payload
        self.labels: list[tuple[int, str]] = []

    def get_pr(self, number):
        return self._pr

    def add_label(self, number, label):
        self.labels.append((number, label))
        return None


def test_awaiting_merge_completes_on_real_merge(tmp_path, cfg: Config) -> None:
    live = Config(target_repo=cfg.target_repo, mode="live", max_files=cfg.max_files)
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(4, "Merging", stage="awaiting_merge", impl_pr=321)
    client = _PrStateClient(live, {"number": 321, "state": "closed", "merged": True})
    p = Poller(config=live, store=store, client=client, graph=Graph())

    result = asyncio.run(p.tick())

    assert result is not None
    assert store.get_issue(4).stage == "merged"


def test_awaiting_merge_escalates_on_closed_unmerged(tmp_path, cfg: Config) -> None:
    live = Config(target_repo=cfg.target_repo, mode="live", max_files=cfg.max_files)
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(5, "Closed", stage="awaiting_merge", impl_pr=321)
    client = _PrStateClient(live, {"number": 321, "state": "closed", "merged": False})
    p = Poller(config=live, store=store, client=client, graph=Graph())

    asyncio.run(p.tick())

    assert store.get_issue(5).stage == "escalated"
    assert (5, "needs-human") in client.labels


def test_awaiting_merge_stays_while_pr_open(tmp_path, cfg: Config) -> None:
    live = Config(target_repo=cfg.target_repo, mode="live", max_files=cfg.max_files)
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(6, "Open", stage="awaiting_merge", impl_pr=321)
    client = _PrStateClient(live, {"number": 321, "state": "open", "merged": False})
    p = Poller(config=live, store=store, client=client, graph=Graph())

    asyncio.run(p.tick())

    assert store.get_issue(6).stage == "awaiting_merge"  # no transition, no phantom
    assert client.labels == []
