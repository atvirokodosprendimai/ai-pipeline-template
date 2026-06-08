from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.graph.nodes.spec import spec_node
from wgmesh_pipeline.goose.runner import GooseResult


@dataclass
class FakeRunner:
    calls: list[dict[str, Any]]

    def run_recipe(self, *, recipe, workdir, params, expected_output):
        output = Path(workdir) / expected_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "# Issue 17 Spec\n\n"
            "## Summary\nWrite the spec.\n\n"
            "## Context\nIssue context.\n\n"
            "## Requirements\n- Requirement.\n\n"
            "## Acceptance Criteria\n- Passes.\n\n"
            "## Out of scope\n- Nothing else.\n"
        )
        self.calls.append(
            {
                "recipe": recipe,
                "workdir": workdir,
                "params": params,
                "expected_output": expected_output,
            }
        )
        return GooseResult(ok=True, output_path=output, duration_seconds=0.01, raw_log="ok")


def test_spec_node_writes_spec_file_with_goose_runner(tmp_path: Path) -> None:
    runner = FakeRunner(calls=[])
    result = spec_node(
        {
            "issue": GitHubIssue(number=17, title="Fix mesh discovery", labels=(), state="open"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
        }
    )

    spec_path = Path(result["spec_path"])
    assert spec_path == tmp_path / "specs/issue-17-spec.md"
    assert spec_path.exists()
    assert "## Acceptance Criteria" in spec_path.read_text()


def test_spec_node_resolves_recipe_path_and_passes_issue_params(tmp_path: Path) -> None:
    runner = FakeRunner(calls=[])
    config = Config(target_repo="atvirokodosprendimai/wgmesh", recipes_dir=str(tmp_path / "recipes"))
    (tmp_path / "recipes").mkdir()

    spec_node(
        {
            "issue": GitHubIssue(number=18, title="Add managed ingress", labels=(), state="open"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "config": config,
        }
    )

    call = runner.calls[0]
    assert call["recipe"] == tmp_path / "recipes" / "wgmesh-triage-spec.yaml"
    assert call["params"] == {
        "issue_number": "18",
        "issue_title": "Add managed ingress",
        "spec_file": "specs/issue-18-spec.md",
    }
