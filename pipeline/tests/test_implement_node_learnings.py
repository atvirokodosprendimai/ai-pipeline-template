from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.goose.runner import GooseResult
from wgmesh_pipeline.graph.nodes.implement import implement_node

DIFF = "diff --git a/x.go b/x.go\n--- a/x.go\n+++ b/x.go\n@@ -1 +1 @@\n-a\n+b\n"


@dataclass
class RecordingRunner:
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    def run_recipe(
        self, *, recipe, workdir, params, expected_output, stage=None, tier=0, session_id=None
    ):
        learnings_path = params.get("learnings_file") or ""
        learnings_content = Path(learnings_path).read_text() if learnings_path else ""
        self.calls.append(
            {
                "params": dict(params),
                "learnings_path": learnings_path,
                "learnings_content": learnings_content,
            }
        )
        out = Path(workdir) / expected_output
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(DIFF)
        if self.fail:
            return GooseResult(
                ok=False, output_path=out, duration_seconds=0.0, raw_log="x", error="fail"
            )
        return GooseResult(ok=True, output_path=out, duration_seconds=0.01, raw_log="ok")


def _issue(number: int, title: str) -> GitHubIssue:
    return GitHubIssue(number=number, title=title, labels=(), state="open")


def _spec_file(tmp_path: Path, text: str) -> Path:
    # non-real path: github absent, spec read from state["spec_path"]
    spec = tmp_path / "specs" / "issue-spec.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(text)
    return spec


def test_learnings_keyed_on_spec_text_from_disk(tmp_path: Path) -> None:
    spec = _spec_file(
        tmp_path,
        "## Approach\nThe goose model must write the spec file, not print it to stdout.\n",
    )
    runner = RecordingRunner()
    implement_node(
        {
            "issue": _issue(70, "Unrelated terse title"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "spec_path": str(spec),
        }
    )
    call = runner.calls[0]
    # the match comes from the SPEC text, not the (unrelated) title
    assert call["params"]["learnings_file"]
    assert "goose" in call["learnings_content"].lower()


def test_spec_read_failure_falls_back_to_title(tmp_path: Path) -> None:
    runner = RecordingRunner()
    result = implement_node(
        {
            # spec_path points nowhere → read fails → title-only query, which
            # still matches the goose learning, proving graceful fallback
            "issue": _issue(71, "goose weak model prints spec to stdout instead of writing"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "spec_path": str(tmp_path / "does-not-exist.md"),
        }
    )
    call = runner.calls[0]
    assert call["params"]["learnings_file"]  # fallback query matched
    assert result["diff"]  # node still ran


def test_no_match_passes_empty_param(tmp_path: Path) -> None:
    spec = _spec_file(tmp_path, "## Approach\nrename a local variable\n")
    runner = RecordingRunner()
    result = implement_node(
        {
            "issue": _issue(72, "xyzzy quux frobnicate"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "spec_path": str(spec),
        }
    )
    call = runner.calls[0]
    assert "learnings_file" in call["params"]  # always passed (required)
    assert call["params"]["learnings_file"] == ""
    assert result["diff"]


def test_selector_failure_is_failopen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from wgmesh_pipeline import learnings as learnings_mod

    def boom(*_args, **_kwargs):
        raise RuntimeError("selector exploded")

    monkeypatch.setattr(learnings_mod, "select_learnings", boom)
    spec = _spec_file(tmp_path, "goose prints spec to stdout instead of writing")
    runner = RecordingRunner()
    result = implement_node(
        {
            "issue": _issue(73, "goose weak model prints spec"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "spec_path": str(spec),
        }
    )
    assert runner.calls[0]["params"]["learnings_file"] == ""
    assert result["diff"]  # proceeded despite selector error


def test_temp_file_cleaned_up_even_on_failure(tmp_path: Path) -> None:
    spec = _spec_file(
        tmp_path, "goose weak model prints spec to stdout instead of writing the file"
    )
    runner = RecordingRunner(fail=True)
    with pytest.raises(RuntimeError):
        implement_node(
            {
                "issue": _issue(74, "Fix relay"),
                "repo_path": tmp_path,
                "goose_runner": runner,
                "spec_path": str(spec),
            }
        )
    learnings_path = runner.calls[0]["learnings_path"]
    assert learnings_path  # a learnings file was created (spec matched)
    assert not Path(learnings_path).exists()  # cleaned up in finally
