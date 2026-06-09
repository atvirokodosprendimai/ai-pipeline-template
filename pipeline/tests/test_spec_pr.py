from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.graph.build import CompiledGraph
from wgmesh_pipeline.graph.nodes.spec import spec_node
from wgmesh_pipeline.graph.nodes.spec_pr import _prepare_spec_branch, spec_pr_node
from wgmesh_pipeline.goose.runner import GooseResult


class RecordingClient:
    def __init__(self, config: Config):
        self.config = config
        self.pushed: list[tuple[str, str]] = []
        self.prs: list[dict[str, Any]] = []
        self.added: list[tuple[int, str]] = []
        self.removed: list[tuple[int, str]] = []
        self.create_pr_targets: list[str] = []

    def push_branch(self, clone_path: str, branch: str, *, spec_pr: bool = False) -> dict[str, Any]:
        self.pushed.append((clone_path, branch))
        return {"ok": True}

    def create_pr(self, **kwargs: Any) -> dict[str, Any]:
        self.prs.append(kwargs)
        self.create_pr_targets.append(self.config.target_repo)
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
    spec_path.write_text("## Classification\nbug\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it\n")
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


class WritingRunner:
    def run_recipe(self, *, recipe, workdir, params, expected_output, stage=None):
        output = Path(workdir) / expected_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "# Issue 17 Spec\n\n"
            "## Classification\nbug\n\n"
            "## Problem Analysis\nThe issue needs a structured implementation spec.\n\n"
            "## Proposed Approach\nPreserve existing discovery behavior while fixing the bug.\n\n"
            "## Acceptance Criteria\n- The discovery fix is covered.\n\n"
            "## Out of scope\n- Unrelated networking changes.\n"
        )
        return GooseResult(ok=True, output_path=output, duration_seconds=0.01, raw_log="ok")


def test_spec_to_spec_pr_commits_spec_file_and_targets_wgmesh(tmp_path: Path) -> None:
    cfg = Config(target_repo="atvirokodosprendimai/wgmesh", mode="spec-only", repo_path=str(tmp_path))
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "bot@example.invalid")
    _git(tmp_path, "config", "user.name", "wgmesh bot")
    _git(tmp_path, "remote", "add", "origin", "https://github.com/atvirokodosprendimai/wgmesh.git")

    client = RecordingClient(cfg)
    issue_17 = issue()
    spec_state = spec_node(
        {
            "issue": issue_17,
            "repo_path": tmp_path,
            "goose_runner": WritingRunner(),
            "config": cfg,
        }
    )
    result = spec_pr_node({**spec_state, "github": client})

    assert result["spec_pr"] == 42
    assert result["spec_branch"] == "bot/spec-17"
    assert client.create_pr_targets == ["atvirokodosprendimai/wgmesh"]
    assert client.prs[0]["head"] == "bot/spec-17"
    assert client.pushed == [(str(tmp_path), "bot/spec-17")]
    assert (tmp_path / "specs/issue-17-spec.md").exists()
    assert _git(tmp_path, "branch", "--show-current").stdout.strip() == "bot/spec-17"
    assert _git(tmp_path, "log", "--format=%s", "-1").stdout.strip() == "spec: Issue #17 - Fix mesh discovery"


def test_prepare_spec_branch_roots_at_origin_main(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    clone = tmp_path / "clone"
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    _git(origin, "config", "user.email", "bot@example.invalid")
    _git(origin, "config", "user.name", "wgmesh bot")
    (origin / "README.md").write_text("wgmesh\n")
    _git(origin, "add", "README.md")
    _git(origin, "commit", "-m", "initial")

    subprocess.run(
        ["git", "clone", str(origin), str(clone)],
        check=True,
        text=True,
        capture_output=True,
    )
    _git(clone, "config", "user.email", "bot@example.invalid")
    _git(clone, "config", "user.name", "wgmesh bot")
    _git(clone, "checkout", "-B", "bot/spec-old")
    stale_spec = clone / "specs" / "issue-1-spec.md"
    stale_spec.parent.mkdir()
    stale_spec.write_text("## Classification\nbug\n")
    _git(clone, "add", str(stale_spec.relative_to(clone)))
    _git(clone, "commit", "-m", "spec: Issue #1 - Stale")

    new_spec = clone / "specs" / "issue-17-spec.md"
    new_spec.write_text("## Classification\nbug\n")

    _prepare_spec_branch(
        clone,
        "bot/spec-17",
        Path("specs/issue-17-spec.md"),
        "spec: Issue #17 - Fix mesh discovery",
    )

    changed_files = _git(clone, "diff", "--name-only", "origin/main..HEAD").stdout.splitlines()
    assert changed_files == ["specs/issue-17-spec.md"]
    assert _git(clone, "branch", "--show-current").stdout.strip() == "bot/spec-17"


def _git(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        text=True,
        capture_output=True,
    )


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


def _resp(code: int):
    import requests
    r = requests.Response()
    r.status_code = code
    return r


def test_spec_pr_idempotent_reuses_existing_pr_on_422(tmp_path: Path) -> None:
    """Retry after a partial run: create_pr 422 -> reuse the existing PR
    instead of failing the node forever (bug #10)."""
    from requests import HTTPError

    cfg = Config(target_repo="atvirokodosprendimai/wgmesh", mode="spec-only")

    class Reraiser(RecordingClient):
        def create_pr(self, **kwargs):
            raise HTTPError(response=_resp(422))

        def find_open_pr_number(self, head_branch: str):
            return 667

        def remove_label(self, issue_number, label, *, spec_pr=False):
            raise HTTPError(response=_resp(404))  # label already gone -> tolerated

    client = Reraiser(cfg)
    state = {
        "issue": GitHubIssue(number=652, title="Fix CI", labels=(), state="open"),
        "github": client,
        "repo_path": str(tmp_path),
        "spec_path": "specs/issue-652-spec.md",
    }
    result = spec_pr_node(state)  # must not raise
    assert result["spec_pr"] == 667
