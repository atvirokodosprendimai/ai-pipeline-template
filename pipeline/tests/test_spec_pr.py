from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.graph.build import CompiledGraph
from wgmesh_pipeline.graph.nodes.spec_pr import spec_pr_node


class RecordingClient:
    def __init__(self, config: Config):
        self.config = config
        self.pushed: list[tuple[str, str]] = []
        self.prs: list[dict[str, Any]] = []
        self.added: list[tuple[int, str]] = []
        self.removed: list[tuple[int, str]] = []

    def push_branch(self, clone_path: str, branch: str, *, spec_pr: bool = False) -> dict[str, Any]:
        self.pushed.append((clone_path, branch))
        return {"ok": True}

    def create_pr(self, **kwargs: Any) -> dict[str, Any]:
        self.prs.append(kwargs)
        return {"number": 42}

    def remove_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> dict[str, Any]:
        self.removed.append((issue_number, label))
        return {"ok": True}

    def add_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> dict[str, Any]:
        self.added.append((issue_number, label))
        return {"ok": True}


@pytest.fixture
def cfg() -> Config:
    return Config(target_repo="atvirokodosprendimai/wgmesh", mode="spec-only")


def issue() -> GitHubIssue:
    return GitHubIssue(number=17, title="Fix mesh discovery", labels=("needs-triage",), state="open")


def test_spec_pr_node_creates_exact_spec_title_and_swaps_labels(tmp_path: Path, cfg: Config) -> None:
    spec_path = tmp_path / "specs" / "issue-17-spec.md"
    spec_path.parent.mkdir()
    spec_path.write_text("## Classification\nfix\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it\n")
    client = RecordingClient(cfg)

    result = spec_pr_node(
        {
            "issue": issue(),
            "github": client,
            "repo_path": tmp_path,
            "spec_path": str(spec_path.relative_to(tmp_path)),
        }
    )

    assert result["spec_pr"] == 42
    assert result["spec_branch"] == "bot/spec-17"
    assert client.pushed == [(str(tmp_path), "bot/spec-17")]
    assert client.prs == [
        {
            "title": "spec: Issue #17 - Fix mesh discovery",
            "head": "bot/spec-17",
            "base": "main",
            "body": "Spec for issue #17.\n\nSpec file: specs/issue-17-spec.md\n",
            "spec_pr": True,
        }
    ]
    assert client.removed == [(17, "needs-triage")]
    assert client.added == [(17, "copilot-triaging")]
    assert result["visited"] == ["spec_pr"]


def test_spec_only_graph_halts_after_spec_pr_before_implementation(cfg: Config) -> None:
    calls: list[str] = []

    def triage(state):
        calls.append("triage")
        return {**state, "classification": "fix"}

    def spec(state):
        calls.append("spec")
        return {**state, "spec_path": "specs/issue-17-spec.md"}

    def spec_pr(state):
        calls.append("spec_pr")
        return {**state, "spec_pr": 42}

    def implement(state):
        calls.append("implement")
        raise AssertionError("implement should not run in spec-only mode")

    def review(state):
        calls.append("review")
        raise AssertionError("review should not run in spec-only mode")

    def gate(state, *, max_files: int):
        calls.append("gate")
        raise AssertionError("gate should not run in spec-only mode")

    graph = CompiledGraph(
        config=cfg,
        triage=triage,
        spec=spec,
        spec_pr=spec_pr,
        implement=implement,
        review=review,
        gate=gate,
    )

    result = graph.invoke({"issue": issue()})

    assert result["spec_pr"] == 42
    assert calls == ["triage", "spec", "spec_pr"]


def test_shadow_graph_still_runs_all_nodes_with_spec_pr_step(cfg: Config) -> None:
    calls: list[str] = []

    def node(name: str, extra: dict[str, Any]):
        def run(state):
            calls.append(name)
            return {**state, **extra}

        return run

    def gate(state, *, max_files: int):
        calls.append("gate")
        return {**state, "decision": "merge"}

    graph = CompiledGraph(
        config=replace(cfg, mode="shadow"),
        triage=node("triage", {"classification": "fix"}),
        spec=node("spec", {"spec_path": "specs/issue-17-spec.md"}),
        spec_pr=node("spec_pr", {"spec_pr": 42}),
        implement=node("implement", {"diff": "+diff\n", "changed_files": ["docs/readme.md"]}),
        review=node("review", {"tests_passed": True, "sanitise_ok": True, "review_findings": []}),
        gate=gate,
    )

    result = graph.invoke({"issue": issue()})

    assert result["decision"] == "merge"
    assert calls == ["triage", "spec", "spec_pr", "implement", "review", "gate"]


def test_live_graph_continues_past_spec_pr_to_gate(cfg: Config) -> None:
    calls: list[str] = []

    def node(name: str, extra: dict[str, Any]):
        def run(state):
            calls.append(name)
            return {**state, **extra}

        return run

    def gate(state, *, max_files: int):
        calls.append("gate")
        return {**state, "decision": "merge"}

    graph = CompiledGraph(
        config=replace(cfg, mode="live", wgmesh_bot_pat="pat"),
        triage=node("triage", {"classification": "fix"}),
        spec=node("spec", {"spec_path": "specs/issue-17-spec.md"}),
        spec_pr=node("spec_pr", {"spec_pr": 42}),
        implement=node("implement", {"diff": "+diff\n", "changed_files": ["docs/readme.md"]}),
        review=node("review", {"tests_passed": True, "sanitise_ok": True, "review_findings": []}),
        gate=gate,
    )

    result = graph.invoke({"issue": issue()})

    assert result["decision"] == "merge"
    assert calls == ["triage", "spec", "spec_pr", "implement", "review", "gate"]
