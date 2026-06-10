from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from requests import HTTPError

from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.graph.nodes.implement import implement_node


class _RecordingClient:
    """Records create_pr / update_pr_body calls so the test can assert R5:
    a retry updates the existing PR, never creates a duplicate."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.push_calls: list[tuple[str, str]] = []
        self.update_calls: list[dict[str, Any]] = []

    def push_branch(self, clone_path: str, branch: str) -> dict[str, Any]:
        self.calls.append(("push_branch", branch))
        self.push_calls.append((clone_path, branch))
        return {"ok": True}

    def create_pr(self, *, title, head, base, body) -> dict[str, Any]:
        self.calls.append(("create_pr", head))
        self.create_calls.append({"title": title, "head": head, "base": base, "body": body})
        return {"number": 4242}

    def update_pr_body(self, pr_number: int, body: str) -> dict[str, Any]:
        self.update_calls.append({"pr_number": pr_number, "body": body})
        return {"number": pr_number}


class _FakeRunner:
    def __init__(self, diff: str | None = None, edit_file: str | None = None, edit_content: str | None = None) -> None:
        self.tiers: list[int] = []
        self.diff = diff or "diff --git a/x.go b/x.go\n+++ b/x.go\n+changed\n"
        self.edit_file = edit_file
        self.edit_content = edit_content
        self.calls: list[dict[str, Any]] = []

    def run_recipe(self, *, recipe, workdir, params, expected_output, stage=None, tier=0, session_id=None):
        self.tiers.append(tier)
        self.calls.append(
            {
                "recipe": recipe,
                "workdir": workdir,
                "params": params,
                "expected_output": expected_output,
                "stage": stage,
                "tier": tier,
            }
        )
        if self.edit_file is not None:
            (Path(workdir) / self.edit_file).write_text(self.edit_content or "")
        out = Path(workdir) / expected_output
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.diff)

        class _R:
            ok = True
            output_path = out
            model_key = f"impl-tier-{tier}"
            error = None

        return _R()


def _base_state(client, runner, tmp_path, *, tier):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "bot@example.invalid")
    _git(tmp_path, "config", "user.name", "wgmesh bot")
    (tmp_path / "README.md").write_text("wgmesh\n")
    spec_path = tmp_path / "specs" / "issue-77-spec.md"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text("spec\n")
    _git(tmp_path, "add", "README.md", "specs/issue-77-spec.md")
    _git(tmp_path, "commit", "-m", "initial")
    return {
        "issue": GitHubIssue(number=77, title="Fix relay", labels=("needs-triage",), state="open"),
        "github": client,
        "goose_runner": runner,
        "repo_path": tmp_path,
        "spec_path": "specs/issue-77-spec.md",
        "escalation_tier": tier,
    }


def test_first_pass_creates_one_pr_no_update(tmp_path) -> None:
    client = _RecordingClient()
    runner = _FakeRunner(edit_file="README.md", edit_content="wgmesh fixed\n")
    out = implement_node(_base_state(client, runner, tmp_path, tier=0))
    assert len(client.create_calls) == 1
    assert client.push_calls == [(str(tmp_path), "bot/impl-77")]
    assert client.update_calls == []
    assert out["impl_pr"] == 4242


def test_retry_updates_existing_pr_no_duplicate(tmp_path) -> None:
    client = _RecordingClient()
    runner = _FakeRunner(edit_file="README.md", edit_content="wgmesh fixed\n")
    # simulate a retry: PR already exists, tier bumped to 1
    state = _base_state(client, runner, tmp_path, tier=1)
    state["impl_pr"] = 4242
    out = implement_node(state)
    # R5: no second PR created
    assert client.create_calls == []
    assert client.push_calls == [(str(tmp_path), "bot/impl-77")]
    # PR body updated, noting the escalated tier + model
    assert len(client.update_calls) == 1
    assert client.update_calls[0]["pr_number"] == 4242
    assert "tier 1" in client.update_calls[0]["body"]
    assert "impl-tier-1" in client.update_calls[0]["body"]
    assert out["impl_pr"] == 4242


def test_retry_reruns_goose_even_with_stale_diff(tmp_path) -> None:
    client = _RecordingClient()
    runner = _FakeRunner(edit_file="README.md", edit_content="wgmesh fixed\n")
    state = _base_state(client, runner, tmp_path, tier=2)
    state["impl_pr"] = 4242
    state["diff"] = "stale\n"  # must NOT short-circuit on a retry pass
    implement_node(state)
    assert runner.tiers == [2]  # Goose re-ran at tier 2


def test_implement_pushes_branch_before_pr(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    clone = tmp_path / "clone"
    _init_origin_with_spec_branch(origin)
    _clone(origin, clone)

    diff = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-wgmesh
+wgmesh fixed
"""
    client = _RecordingClient()
    runner = _FakeRunner(diff, edit_file="README.md", edit_content="wgmesh fixed\n")

    result = implement_node(
        {
            "issue": GitHubIssue(number=77, title="Fix relay", labels=("needs-triage",), state="open"),
            "github": client,
            "goose_runner": runner,
            "repo_path": clone,
            "spec_path": "specs/issue-77-spec.md",
        }
    )

    assert result["impl_pr"] == 4242
    assert client.calls[:2] == [("push_branch", "bot/impl-77"), ("create_pr", "bot/impl-77")]
    assert _git(clone, "branch", "--show-current").stdout.strip() == "bot/impl-77"
    assert _git(clone, "diff", "--name-only", "origin/main..HEAD").stdout.splitlines() == ["README.md"]
    assert _git(clone, "show", "HEAD:README.md").stdout == "wgmesh fixed\n"
    assert _git(clone, "log", "--format=%s", "-1").stdout.strip() == "impl: Issue #77 - Fix relay"


def test_implement_starts_from_clean_workspace(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    clone = tmp_path / "clone"
    _init_origin_with_spec_branch(origin)
    _clone(origin, clone)
    _git(clone, "checkout", "-B", "bot/spec-77", "origin/bot/spec-77")
    (clone / "main.go").write_text("package main\n\nfunc main() { println(\"contaminated\") }\n")

    diff = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-wgmesh
+wgmesh fixed
"""
    client = _RecordingClient()
    runner = _FakeRunner(diff, edit_file="README.md", edit_content="wgmesh fixed\n")

    result = implement_node(
        {
            "issue": GitHubIssue(number=77, title="Fix relay", labels=("needs-triage",), state="open"),
            "github": client,
            "goose_runner": runner,
            "repo_path": clone,
            "spec_path": "specs/issue-77-spec.md",
        }
    )

    assert result["impl_pr"] == 4242
    assert client.calls[:2] == [("push_branch", "bot/impl-77"), ("create_pr", "bot/impl-77")]
    assert _git(clone, "diff", "--name-only", "origin/main..HEAD").stdout.splitlines() == ["README.md"]
    assert _git(clone, "show", "HEAD:README.md").stdout == "wgmesh fixed\n"
    assert _git(clone, "show", "HEAD:main.go").stdout == "package main\n\nfunc main() {}\n"
    assert result["diff"].startswith("diff --git a/README.md b/README.md")
    assert "main.go" not in result["diff"]
    assert result["changed_files"] == ["README.md"]


def test_implement_materializes_spec_from_spec_branch(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    clone = tmp_path / "clone"
    _init_origin_with_spec_branch(origin)
    _clone(origin, clone)
    seen: dict[str, str] = {}

    class SpecAssertingRunner(_FakeRunner):
        def run_recipe(self, *, recipe, workdir, params, expected_output, stage=None, tier=0, session_id=None):
            spec_file = Path(params["spec_file"])
            assert spec_file.parts[0] == "pipeline-output"
            materialized = Path(workdir) / spec_file
            assert materialized.exists()
            seen["spec_file"] = str(spec_file)
            seen["content"] = materialized.read_text()
            return super().run_recipe(
                recipe=recipe,
                workdir=workdir,
                params=params,
                expected_output=expected_output,
                stage=stage,
                tier=tier,
            )

    runner = SpecAssertingRunner(
        "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-wgmesh\n+wgmesh fixed\n",
        edit_file="README.md",
        edit_content="wgmesh fixed\n",
    )

    implement_node(
        {
            "issue": GitHubIssue(number=77, title="Fix relay", labels=("needs-triage",), state="open"),
            "github": _RecordingClient(),
            "goose_runner": runner,
            "repo_path": clone,
            "spec_path": "specs/issue-77-spec.md",
        }
    )

    assert seen == {
        "spec_file": "pipeline-output/issue-77-spec.md",
        "content": "spec branch content\n",
    }


def test_implement_no_changes_fails_loudly(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    clone = tmp_path / "clone"
    _init_origin_with_spec_branch(origin)
    _clone(origin, clone)

    with pytest.raises(RuntimeError, match="no tree changes"):
        implement_node(
            {
                "issue": GitHubIssue(number=77, title="Fix relay", labels=("needs-triage",), state="open"),
                "github": _RecordingClient(),
                "goose_runner": _FakeRunner(),
                "repo_path": clone,
                "spec_path": "specs/issue-77-spec.md",
            }
        )


def test_ensure_impl_pr_reuses_existing_on_422(tmp_path: Path) -> None:
    response = type("Response", (), {"status_code": 422})()

    class ExistingPrClient(_RecordingClient):
        def __init__(self) -> None:
            super().__init__()
            self.lookups: list[str] = []

        def create_pr(self, *, title, head, base, body):
            raise HTTPError("422 :: A pull request already exists", response=response)

        def find_open_pr_number(self, head_branch: str) -> int:
            self.lookups.append(head_branch)
            return 909

    client = ExistingPrClient()
    result = implement_node(
        {
            "issue": GitHubIssue(number=77, title="Fix relay", labels=("needs-triage",), state="open"),
            "github": client,
            "diff": "diff --git a/README.md b/README.md\n+++ b/README.md\n+changed\n",
            "repo_path": tmp_path,
        }
    )

    assert result["impl_pr"] == 909
    assert client.lookups == ["bot/impl-77"]


def _git(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        text=True,
        capture_output=True,
    )


def _clone(origin: Path, clone: Path) -> None:
    subprocess.run(
        ["git", "clone", str(origin), str(clone)],
        check=True,
        text=True,
        capture_output=True,
    )


def _init_origin_with_spec_branch(origin: Path) -> None:
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    _git(origin, "config", "user.email", "bot@example.invalid")
    _git(origin, "config", "user.name", "wgmesh bot")
    (origin / "README.md").write_text("wgmesh\n")
    (origin / "main.go").write_text("package main\n\nfunc main() {}\n")
    _git(origin, "add", "README.md", "main.go")
    _git(origin, "commit", "-m", "initial")
    _git(origin, "checkout", "-b", "bot/spec-77")
    (origin / "specs").mkdir()
    (origin / "specs" / "issue-77-spec.md").write_text("spec branch content\n")
    _git(origin, "add", "specs/issue-77-spec.md")
    _git(origin, "commit", "-m", "spec")
    _git(origin, "checkout", "main")
