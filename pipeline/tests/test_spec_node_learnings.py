from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.goose.runner import GooseResult
from wgmesh_pipeline.graph.nodes.spec import spec_node


@dataclass
class RecordingRunner:
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    def run_recipe(self, *, recipe, workdir, params, expected_output, stage=None, session_id=None):
        # Capture learnings_file content WHILE it exists (spec_node unlinks it in
        # a finally), plus the tmp paths so the test can assert cleanup.
        learnings_path = params.get("learnings_file") or ""
        learnings_content = (
            Path(learnings_path).read_text() if learnings_path else ""
        )
        self.calls.append(
            {
                "params": dict(params),
                "learnings_path": learnings_path,
                "learnings_content": learnings_content,
            }
        )
        output = Path(workdir) / expected_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "# Spec\n\n## Classification\nfeature\n\n## Problem Analysis\nx\n\n"
            "## Proposed Approach\nx\n\n## Acceptance Criteria\n- ok\n\n"
            "## Out of scope\n- none\n"
        )
        if self.fail:
            return GooseResult(
                ok=False, output_path=output, duration_seconds=0.0, raw_log="boom", error="fail"
            )
        return GooseResult(ok=True, output_path=output, duration_seconds=0.01, raw_log="ok")


def _issue(number: int, title: str) -> GitHubIssue:
    return GitHubIssue(number=number, title=title, labels=(), state="open")


def test_matching_issue_passes_nonempty_learnings_file(tmp_path: Path) -> None:
    runner = RecordingRunner()
    spec_node(
        {
            # title overlaps the goose-weak-model learning's tags/title
            "issue": _issue(91, "goose weak model prints spec to stdout instead of writing"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
        }
    )
    call = runner.calls[0]
    assert call["params"]["learnings_file"]  # non-empty path
    assert call["params"]["learnings_file"].endswith(".md")
    assert "Past learning:" in call["learnings_content"]
    assert "goose" in call["learnings_content"].lower()


def test_no_match_issue_passes_empty_param_and_runs(tmp_path: Path) -> None:
    runner = RecordingRunner()
    result = spec_node(
        {
            "issue": _issue(92, "xyzzy quux frobnicate unrelated"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
        }
    )
    call = runner.calls[0]
    assert "learnings_file" in call["params"]  # always passed (required)
    assert call["params"]["learnings_file"] == ""  # no match → empty path
    assert result["spec_path"]  # node still completed normally


def test_selector_failure_is_failopen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("selector exploded")

    # spec_node -> write_learnings_file -> select_learnings (module global).
    # Patch the underlying selector to raise; write_learnings_file's own
    # fail-open must swallow it and return "" so the spec run proceeds.
    from wgmesh_pipeline import learnings as learnings_mod

    monkeypatch.setattr(learnings_mod, "select_learnings", boom)

    runner = RecordingRunner()
    result = spec_node(
        {
            "issue": _issue(93, "goose weak model prints spec"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
        }
    )
    assert runner.calls[0]["params"]["learnings_file"] == ""
    assert result["spec_path"]  # run proceeded despite selector error


def test_temp_learnings_file_cleaned_up_even_on_failure(tmp_path: Path) -> None:
    runner = RecordingRunner(fail=True)
    with pytest.raises(RuntimeError):
        spec_node(
            {
                "issue": _issue(94, "goose weak model prints spec to stdout instead of writing"),
                "repo_path": tmp_path,
                "goose_runner": runner,
                "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
            }
        )
    learnings_path = runner.calls[0]["learnings_path"]
    assert learnings_path  # a learnings file was created for this matching issue
    assert not Path(learnings_path).exists()  # cleaned up in finally
