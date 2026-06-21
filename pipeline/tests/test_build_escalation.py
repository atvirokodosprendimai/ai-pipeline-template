from __future__ import annotations

from dataclasses import replace

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue
from wgmesh_pipeline.graph.build import CompiledGraph
from wgmesh_pipeline.graph.nodes.gate import gate_node


def _cfg(
    *,
    mode: str = "shadow",
    ladder: tuple[str, ...] = ("cheap", "capable"),
    max_attempts: int = 2,
) -> Config:
    return Config(
        target_repo="atvirokodosprendimai/wgmesh",
        mode=mode,
        max_files=3,
        stage_routing={"implement": ladder},
        max_escalation_attempts=max_attempts,
    )


def _graph(config: Config, *, implement, review) -> CompiledGraph:
    return CompiledGraph(
        config=config,
        triage=_node("triage", classification="fix"),
        spec=_node("spec", spec_path="specs/issue-1-spec.md"),
        spec_pr=_node("spec_pr", spec_pr=101),
        implement=implement,
        review=review,
        gate=gate_node,
    )


def _node(name: str, **updates):
    def run(state):
        next_state = dict(state)
        next_state.setdefault("visited", []).append(name)
        next_state.update(updates)
        return next_state

    return run


def _implement():
    def run(state):
        next_state = dict(state)
        tier = int(next_state.get("escalation_tier", 0))
        next_state.setdefault("visited", []).append("implement")
        next_state["diff"] = f"diff --git a/docs/tier-{tier}.md b/docs/tier-{tier}.md\n+docs\n"
        next_state["changed_files"] = [f"docs/tier-{tier}.md"]
        next_state["impl_pr"] = 123
        return next_state

    return run


def _review_by_tier(results: dict[int, dict]):
    def run(state):
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


def _state(client: GitHubClient | None = None):
    return {
        "issue": GitHubIssue(number=1, title="Fix docs", labels=("needs-triage", "surface:product"), state="open"),
        "github": client,
    }


def test_tier_zero_fails_tests_tier_one_passes_merges_once() -> None:
    client = GitHubClient(_cfg())
    graph = _graph(
        _cfg(),
        implement=_implement(),
        review=_review_by_tier({0: {"tests_passed": False}, 1: {"tests_passed": True}}),
    )

    result = graph.invoke(_state(client))

    assert result["decision"] == "merge"
    assert result["escalation_history"] == [0, 1]
    assert result["escalation_attempts"] == 1
    assert [record.operation for record in client.dry_run_records] == ["enable_auto_merge"]


def test_tier_zero_fails_ladder_length_one_does_not_retry() -> None:
    client = GitHubClient(_cfg(ladder=("cheap",)))
    graph = _graph(
        _cfg(ladder=("cheap",)),
        implement=_implement(),
        review=_review_by_tier({0: {"tests_passed": False}}),
    )

    result = graph.invoke(_state(client))

    assert result["decision"] == "escalate"
    assert result["escalation_history"] == [0]
    assert [record.operation for record in client.dry_run_records] == ["add_label"]


def test_hard_gate_sanitise_failure_does_not_retry() -> None:
    client = GitHubClient(_cfg(ladder=("cheap", "capable", "premium")))
    graph = _graph(
        _cfg(ladder=("cheap", "capable", "premium")),
        implement=_implement(),
        review=_review_by_tier({0: {"tests_passed": False, "sanitise_ok": False}}),
    )

    result = graph.invoke(_state(client))

    assert result["decision"] == "escalate"
    assert result["retryable"] is False
    assert result["escalation_history"] == [0]
    assert [record.operation for record in client.dry_run_records] == ["add_label"]


def test_max_escalation_attempts_caps_retries_before_ladder_top() -> None:
    client = GitHubClient(_cfg(ladder=("cheap", "capable", "premium"), max_attempts=1))
    graph = _graph(
        _cfg(ladder=("cheap", "capable", "premium"), max_attempts=1),
        implement=_implement(),
        review=_review_by_tier({0: {"tests_passed": False}, 1: {"tests_passed": False}}),
    )

    result = graph.invoke(_state(client))

    assert result["decision"] == "escalate"
    assert result["escalation_history"] == [0, 1]
    assert result["escalation_attempts"] == 1
    assert [record.operation for record in client.dry_run_records] == ["add_label"]


def test_all_tiers_fail_quality_exhausts_to_human() -> None:
    client = GitHubClient(_cfg(ladder=("cheap", "capable", "premium"), max_attempts=2))
    graph = _graph(
        _cfg(ladder=("cheap", "capable", "premium"), max_attempts=2),
        implement=_implement(),
        review=_review_by_tier(
            {
                0: {"tests_passed": False},
                1: {"tests_passed": False},
                2: {"tests_passed": False},
            }
        ),
    )

    result = graph.invoke(_state(client))

    assert result["decision"] == "escalate"
    assert result["escalation_history"] == [0, 1, 2]
    assert [record.operation for record in client.dry_run_records] == ["add_label"]


def test_no_needs_human_label_on_intermediate_failing_pass() -> None:
    client = GitHubClient(_cfg())
    graph = _graph(
        _cfg(),
        implement=_implement(),
        review=_review_by_tier({0: {"tests_passed": False}, 1: {"tests_passed": True}}),
    )

    graph.invoke(_state(client))

    assert [record.operation for record in client.dry_run_records] == ["enable_auto_merge"]


def test_spec_only_mode_never_enters_escalation_loop() -> None:
    calls: list[str] = []

    def implement(state):
        calls.append("implement")
        return dict(state)

    config = replace(_cfg(mode="spec-only"), mode="spec-only")
    graph = _graph(config, implement=implement, review=_review_by_tier({}))

    result = graph.invoke(_state(GitHubClient(config)))

    assert calls == []
    assert result["visited"] == ["triage", "surface_gate", "spec", "spec_pr"]
    assert "escalation_history" not in result


def test_clean_tier_zero_build_merges_without_escalation() -> None:
    client = GitHubClient(_cfg())
    graph = _graph(
        _cfg(),
        implement=_implement(),
        review=_review_by_tier({0: {"tests_passed": True}}),
    )

    result = graph.invoke(_state(client))

    assert result["decision"] == "merge"
    assert result["escalation_history"] == [0]
    assert result["escalation_attempts"] == 0
    assert [record.operation for record in client.dry_run_records] == ["enable_auto_merge"]
