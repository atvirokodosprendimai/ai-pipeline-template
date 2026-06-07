from __future__ import annotations

import asyncio

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient
from wgmesh_pipeline.graph.build import build_graph
from wgmesh_pipeline.poller import Poller
from wgmesh_pipeline.state.store import StateStore


class EmptyClient(GitHubClient):
    def list_open_issues(self):
        return []


class Graph:
    def __init__(self):
        self.calls: list[str] = []

    def triage(self, state):
        self.calls.append("triage")
        return {**state, "classification": "fix"}

    def spec(self, state):
        self.calls.append("spec")
        return {**state, "spec_path": "specs/issue.md"}

    def implement(self, state):
        self.calls.append("implement")
        return {**state, "diff": "+diff\n", "changed_files": ["docs/readme.md"]}

    def review(self, state):
        self.calls.append("review")
        return {**state, "tests_passed": True, "sanitise_ok": True, "review_findings": []}


@pytest.fixture
def cfg() -> Config:
    return Config(target_repo="atvirokodosprendimai/wgmesh", mode="shadow", max_files=3)


def poller(tmp_path, cfg: Config, graph=None):
    store = StateStore(tmp_path / "state.db")
    client = EmptyClient(cfg)
    return Poller(config=cfg, store=store, client=client, graph=graph or Graph())


def test_tick_advances_queued_issue_to_triaged_and_records_run(tmp_path, cfg: Config) -> None:
    p = poller(tmp_path, cfg)
    p.store.upsert_issue(1, "Fix bug")

    result = asyncio.run(p.tick())

    assert result is not None
    assert result.stage == "triaged"
    assert p.store.get_issue(1).classification == "fix"
    assert p.store.list_runs()[0]["node"] == "queued"
    assert p.store.list_runs()[0]["outcome"] == "ok"


def test_tick_no_actionable_issue_is_noop(tmp_path, cfg: Config) -> None:
    p = poller(tmp_path, cfg)

    result = asyncio.run(p.tick())

    assert result is None
    assert p.store.list_runs() == []


def test_graph_exception_bumps_attempt_and_loop_continues(tmp_path, cfg: Config) -> None:
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


def test_restart_mid_flight_resumes_persisted_stage_without_double_work(tmp_path, cfg: Config) -> None:
    db_path = tmp_path / "state.db"
    StateStore(db_path).upsert_issue(1, "Already triaged", stage="triaged")
    graph = Graph()
    restarted = Poller(config=cfg, store=StateStore(db_path), client=EmptyClient(cfg), graph=graph)

    result = asyncio.run(restarted.tick())

    assert result is not None
    assert result.stage == "specced"
    assert graph.calls == ["spec"]


def test_main_graph_shadow_fixture_can_complete_full_cycle_without_writes(tmp_path, cfg: Config, monkeypatch) -> None:
    monkeypatch.setattr("wgmesh_pipeline.graph.nodes.review.run_sanitise", lambda text: True)
    client = EmptyClient(cfg)
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(1, "Fix docs")
    p = Poller(config=cfg, store=store, client=client, graph=build_graph(cfg))

    for _ in range(5):
        asyncio.run(p.tick())

    assert store.get_issue(1).stage == "merged"
    assert [record.operation for record in client.dry_run_records] == ["merge_pr"]
