from __future__ import annotations

from dataclasses import dataclass

from wgmesh_pipeline.config import Config, load_config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.graph import build_lg
from wgmesh_pipeline.graph.build import CompiledGraph, build_graph
from wgmesh_pipeline.graph.nodes.gate import gate_node
from wgmesh_pipeline.graph.state import GraphState


def _cfg(
    *,
    mode: str = "shadow",
    ladder: tuple[str, ...] = ("cheap", "capable"),
    max_attempts: int = 2,
    graph_impl: str = "legacy",
) -> Config:
    return Config(
        target_repo="atvirokodosprendimai/wgmesh",
        mode=mode,
        max_files=3,
        stage_routing={"implement": ladder},
        max_escalation_attempts=max_attempts,
        graph_impl=graph_impl,
    )


@dataclass
class RecordingClient:
    config: Config
    calls: list[tuple] | None = None

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    def add_label(self, issue_number: int, label: str) -> None:
        self.calls.append(("add_label", issue_number, label))

    def merge_pr(self, pr_number: int, *, commit_title: str) -> None:
        self.calls.append(("merge_pr", pr_number, commit_title))


@dataclass(frozen=True)
class Nodes:
    triage: object
    spec: object
    spec_pr: object
    implement: object
    review: object


def _node(name: str, **updates):
    def run(state: GraphState) -> GraphState:
        next_state = dict(state)
        next_state.setdefault("visited", []).append(name)
        next_state.update(updates)
        return next_state

    return run


def _implement():
    def run(state: GraphState) -> GraphState:
        next_state = dict(state)
        tier = int(next_state.get("escalation_tier", 0))
        next_state.setdefault("visited", []).append("implement")
        next_state["diff"] = (
            f"diff --git a/docs/tier-{tier}.md b/docs/tier-{tier}.md\n+docs\n"
        )
        next_state["changed_files"] = [f"docs/tier-{tier}.md"]
        next_state["impl_pr"] = 123
        return next_state

    return run


def _review_by_tier(results: dict[int, dict]):
    def run(state: GraphState) -> GraphState:
        next_state = dict(state)
        tier = int(next_state.get("escalation_tier", 0))
        next_state.setdefault("visited", []).append("review")
        next_state.update(
            {
                "tests_passed": True,
                "sanitise_ok": True,
                "review_findings": [],
                **results.get(tier, {}),
            }
        )
        return next_state

    return run


def _nodes(
    *,
    classification: str = "fix",
    review_results: dict[int, dict] | None = None,
) -> Nodes:
    return Nodes(
        triage=_node("triage", classification=classification),
        spec=_node("spec", spec_path="specs/issue-1-spec.md"),
        spec_pr=_node("spec_pr", spec_pr=101),
        implement=_implement(),
        review=_review_by_tier(review_results or {}),
    )


def _state(client: RecordingClient) -> GraphState:
    return {
        "issue": GitHubIssue(
            number=1,
            title="Fix docs",
            labels=("needs-triage",),
            state="open",
        ),
        "github": client,
    }


def _assert_parity(
    monkeypatch,
    *,
    config: Config,
    nodes: Nodes,
    expected_calls: list[tuple],
) -> GraphState:
    monkeypatch.setattr(build_lg, "triage_node", nodes.triage)
    monkeypatch.setattr(build_lg, "spec_node", nodes.spec)
    monkeypatch.setattr(build_lg, "spec_pr_node", nodes.spec_pr)
    monkeypatch.setattr(build_lg, "implement_node", nodes.implement)
    monkeypatch.setattr(build_lg, "review_node", nodes.review)

    legacy_client = RecordingClient(config)
    langgraph_client = RecordingClient(config)
    legacy = CompiledGraph(
        config=config,
        triage=nodes.triage,
        spec=nodes.spec,
        spec_pr=nodes.spec_pr,
        implement=nodes.implement,
        review=nodes.review,
        gate=gate_node,
    )
    langgraph = build_lg.build_state_graph(config)

    legacy_result = legacy.invoke(_state(legacy_client))
    langgraph_result = langgraph.invoke(_state(langgraph_client))

    assert legacy_result == langgraph_result
    assert legacy_client.calls == expected_calls
    assert langgraph_client.calls == expected_calls
    return langgraph_result


def test_langgraph_parity_wont_do_triage_escalates_without_gate_side_effects(
    monkeypatch,
) -> None:
    result = _assert_parity(
        monkeypatch,
        config=_cfg(),
        nodes=_nodes(classification="wont-do"),
        expected_calls=[("add_label", 1, "needs-human")],
    )

    assert result["decision"] == "escalate"
    assert result["visited"] == ["triage", "escalate"]


def test_langgraph_parity_needs_info_triage_escalates_without_gate_side_effects(
    monkeypatch,
) -> None:
    result = _assert_parity(
        monkeypatch,
        config=_cfg(),
        nodes=_nodes(classification="needs-info"),
        expected_calls=[("add_label", 1, "needs-human")],
    )

    assert result["decision"] == "escalate"
    assert result["visited"] == ["triage", "escalate"]


def test_langgraph_parity_spec_only_stops_after_spec_pr(monkeypatch) -> None:
    result = _assert_parity(
        monkeypatch,
        config=_cfg(mode="spec-only"),
        nodes=_nodes(classification="feature"),
        expected_calls=[],
    )

    assert result["visited"] == ["triage", "spec", "spec_pr"]
    assert "decision" not in result
    assert "escalation_history" not in result


def test_langgraph_parity_full_live_path_merges_after_gate_side_effects(
    monkeypatch,
) -> None:
    result = _assert_parity(
        monkeypatch,
        config=_cfg(),
        nodes=_nodes(review_results={0: {"tests_passed": True}}),
        expected_calls=[("merge_pr", 123, "Merge issue #1")],
    )

    assert result["decision"] == "merge"
    assert result["visited"] == [
        "triage",
        "spec",
        "spec_pr",
        "implement",
        "review",
        "gate",
    ]


def test_langgraph_parity_retryable_failure_retries_next_tier_then_merges(
    monkeypatch,
) -> None:
    result = _assert_parity(
        monkeypatch,
        config=_cfg(ladder=("cheap", "capable")),
        nodes=_nodes(
            review_results={
                0: {"tests_passed": False},
                1: {"tests_passed": True},
            }
        ),
        expected_calls=[("merge_pr", 123, "Merge issue #1")],
    )

    assert result["decision"] == "merge"
    assert result["escalation_history"] == [0, 1]
    assert result["escalation_attempts"] == 1


def test_langgraph_parity_retryable_failure_exhausts_at_ladder_length(
    monkeypatch,
) -> None:
    result = _assert_parity(
        monkeypatch,
        config=_cfg(ladder=("cheap",)),
        nodes=_nodes(review_results={0: {"tests_passed": False}}),
        expected_calls=[("add_label", 1, "needs-human")],
    )

    assert result["decision"] == "escalate"
    assert result["retryable"] is True
    assert result["escalation_history"] == [0]


def test_langgraph_parity_retryable_failure_exhausts_at_max_attempts(
    monkeypatch,
) -> None:
    result = _assert_parity(
        monkeypatch,
        config=_cfg(ladder=("cheap", "capable", "premium"), max_attempts=1),
        nodes=_nodes(
            review_results={
                0: {"tests_passed": False},
                1: {"tests_passed": False},
            }
        ),
        expected_calls=[("add_label", 1, "needs-human")],
    )

    assert result["decision"] == "escalate"
    assert result["retryable"] is True
    assert result["escalation_history"] == [0, 1]
    assert result["escalation_attempts"] == 1


def test_langgraph_parity_non_retryable_failure_escalates(monkeypatch) -> None:
    result = _assert_parity(
        monkeypatch,
        config=_cfg(ladder=("cheap", "capable", "premium")),
        nodes=_nodes(review_results={0: {"tests_passed": False, "sanitise_ok": False}}),
        expected_calls=[("add_label", 1, "needs-human")],
    )

    assert result["decision"] == "escalate"
    assert result["retryable"] is False
    assert result["escalation_history"] == [0]


def test_build_graph_langgraph_flag_dispatches_and_exposes_poller_nodes() -> None:
    config = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
            "GRAPH_IMPL": " LangGraph ",
        }
    )

    graph = build_graph(config)

    assert config.graph_impl == "langgraph"
    assert isinstance(graph, build_lg.StateGraphWrapper)
    assert graph.config is config
    for name in ("triage", "spec", "spec_pr", "implement", "review", "gate"):
        assert hasattr(graph, name)
