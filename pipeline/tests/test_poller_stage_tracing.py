from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.graph import build_lg
from wgmesh_pipeline.graph.state import GraphState

pytestmark = pytest.mark.unit


STAGES = ("triage", "spec", "spec_pr", "implement", "review")
STAGE_UPDATES = {
    "triage": {"classification": "fix"},
    "spec": {"spec_path": "specs/issue-7-spec.md"},
    "spec_pr": {"spec_pr": 107},
    "implement": {"impl_pr": 207, "changed_files": ["README.md"]},
    "review": {"tests_passed": True, "sanitise_ok": True},
}


def _cfg() -> Config:
    return Config(target_repo="atvirokodosprendimai/wgmesh")


def _state(*, issue_number: int | None = 7) -> GraphState:
    state: GraphState = {"visited": []}
    if issue_number is not None:
        state["issue"] = GitHubIssue(
            number=issue_number,
            title="Trace poller stage",
            labels=("fn:dev",),
            state="open",
        )
    return state


def _node(name: str):
    def run(state: GraphState) -> GraphState:
        next_state = dict(state)
        next_state["visited"] = [*next_state.get("visited", []), name]
        next_state.update(STAGE_UPDATES[name])
        return next_state

    return run


@dataclass
class FakeStageGraph:
    result: GraphState | None = None
    configs: list[dict | None] = field(default_factory=list)

    def invoke(self, state: GraphState, config: dict | None = None) -> GraphState:
        self.configs.append(config)
        return self.result if self.result is not None else state


@pytest.fixture
def fake_nodes(monkeypatch):
    nodes = {name: _node(name) for name in STAGES}
    for name, fn in nodes.items():
        monkeypatch.setattr(build_lg, f"{name}_node", fn)
    return nodes


def test_poller_stage_calls_match_raw_node_results(fake_nodes) -> None:
    wrapper = build_lg.build_state_graph(_cfg())

    for name in STAGES:
        state = _state()
        expected = fake_nodes[name](state)

        result = getattr(wrapper, name)(_state())

        assert result == expected


def test_poller_stage_calls_attach_callback_handler(monkeypatch, fake_nodes) -> None:
    fake_handler = object()
    wrapper = build_lg.build_state_graph(_cfg())
    stage_graphs = {name: FakeStageGraph(result={"stage": name}) for name in STAGES}
    wrapper._stage_graphs = stage_graphs
    monkeypatch.setattr(build_lg, "build_callback_handler", lambda config: fake_handler)

    for name in STAGES:
        result = getattr(wrapper, name)(_state())

        assert result == {"stage": name}
        assert stage_graphs[name].configs == [{"callbacks": [fake_handler]}]


def test_poller_stage_calls_invoke_plainly_without_handler(
    monkeypatch,
    fake_nodes,
) -> None:
    wrapper = build_lg.build_state_graph(_cfg())
    stage_graph = FakeStageGraph(result={"ok": True})
    wrapper._stage_graphs = {"triage": stage_graph}
    monkeypatch.setattr(build_lg, "build_callback_handler", lambda config: None)

    result = wrapper.triage(_state())

    assert result == {"ok": True}
    assert stage_graph.configs == [None]


def test_poller_stage_calls_group_issue_session(monkeypatch, fake_nodes) -> None:
    sessions: list[str | None] = []
    wrapper = build_lg.build_state_graph(_cfg())
    wrapper._stage_graphs = {"triage": FakeStageGraph(result={"ok": True})}
    monkeypatch.setattr(build_lg, "build_callback_handler", lambda config: object())

    @contextmanager
    def record_session(session_id: str | None):
        sessions.append(session_id)
        yield

    monkeypatch.setattr(build_lg, "_session_id_ctx", record_session)

    result = wrapper.triage(_state(issue_number=7))

    assert result == {"ok": True}
    assert sessions == ["issue-7"]


def test_poller_stage_tracing_setup_failure_is_non_fatal(
    monkeypatch,
    fake_nodes,
) -> None:
    wrapper = build_lg.build_state_graph(_cfg())
    stage_graph = FakeStageGraph(result={"ok": True})
    wrapper._stage_graphs = {"triage": stage_graph}

    def boom(config):
        raise RuntimeError("callback unavailable")

    monkeypatch.setattr(build_lg, "build_callback_handler", boom)

    result = wrapper.triage(_state())

    assert result == {"ok": True}
    assert stage_graph.configs == [None]
