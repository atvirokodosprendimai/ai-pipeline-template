from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.graph.nodes.spec import _spec_malformed_reason, spec_node
from wgmesh_pipeline.goose.runner import GooseResult


@dataclass
class FakeRunner:
    calls: list[dict[str, Any]]

    def run_recipe(self, *, recipe, workdir, params, expected_output, stage=None, session_id=None):
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
        # Capture the brief file's content WHILE it exists — spec_node unlinks
        # it in a finally, so it's gone by the time the test asserts.
        brief_path = params.get("issue_brief_file") or ""
        brief_content = Path(brief_path).read_text() if brief_path else ""
        self.calls.append(
            {
                "recipe": recipe,
                "workdir": workdir,
                "params": params,
                "expected_output": expected_output,
                "brief_content": brief_content,
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
        "issue_brief_file": "",  # no body in state → empty path → title fallback
        "learnings_file": "",  # title matches no learning → empty path (always passed)
        "spec_file": "specs/issue-18-spec.md",
    }


def test_spec_node_hands_the_brief_to_the_recipe_as_a_file(tmp_path: Path) -> None:
    # The PM brief (issue_body) must reach the builder as a file path (it is
    # multi-line, so it can't be an inline recipe param), and the file must
    # carry the brief verbatim.
    runner = FakeRunner(calls=[])
    brief = "## Problem\nTrial drop-off.\n## ROI / Impact\n+5% conversion.\n"
    spec_node(
        {
            "issue": GitHubIssue(number=42, title="Onboarding fix", labels=(), state="open"),
            "issue_body": brief,
            "repo_path": tmp_path,
            "goose_runner": runner,
            "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
        }
    )

    call = runner.calls[0]
    assert call["params"]["issue_brief_file"]  # non-empty path
    assert call["params"]["issue_brief_file"].endswith(".md")
    assert call["brief_content"] == brief


def test_spec_node_puts_spec_content_in_state_for_judge(tmp_path: Path) -> None:
    """The authored spec text rides in state -> trace_node includes it in the
    'spec' span output so a managed Langfuse LLM-as-a-Judge can score it."""
    runner = FakeRunner(calls=[])
    result = spec_node(
        {
            "issue": GitHubIssue(number=17, title="Fix mesh discovery", labels=(), state="open"),
            "repo_path": tmp_path,
            "goose_runner": runner,
            "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
        }
    )
    assert "## Acceptance Criteria" in result["spec_content"]
    assert result["spec_content"].startswith("# Issue 17 Spec")


def test_spec_node_no_runner_has_no_spec_content(tmp_path: Path) -> None:
    result = spec_node(
        {
            "issue": GitHubIssue(number=18, title="x", labels=(), state="open"),
            "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
            "repo_path": tmp_path,
        }
    )
    assert "spec_content" not in result  # no-op path writes no file


# ---- malformed-spec gate (issue #783: goose dumped a 3672-line transcript with a
# truncated write-tool call as the "spec"; result.ok only checks the file is
# non-empty, so the garbage spec advanced to implement and produced off-spec code) --

# The exact markers seen on the #783 transcript-spec; absent from clean specs (#779).
_TRANSCRIPT_SPEC = (
    "   __( O)>  ● new session · anthropic glm-4.6\n"
    " \\____)    goose is ready\n"
    "I'll create an implementation specification. Let me explore.\n"
    "  ▸ tree\n"
    "...3000 lines of exploration...\n"
    "-32602: Could not parse tool arguments: the response may have been truncated.\n"
)


@dataclass
class MalformedRunner:
    content: str

    def run_recipe(self, *, recipe, workdir, params, expected_output, stage=None, session_id=None):
        output = Path(workdir) / expected_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.content)
        return GooseResult(ok=True, output_path=output, duration_seconds=0.01, raw_log="ok")


def test_spec_node_rejects_transcript_spec(tmp_path: Path) -> None:
    # result.ok is True (file exists, non-empty) but the content is a goose
    # transcript with a truncated write — must fail like any other spec failure
    # so it never advances to implement.
    runner = MalformedRunner(content=_TRANSCRIPT_SPEC)
    with pytest.raises(RuntimeError, match="malformed spec"):
        spec_node(
            {
                "issue": GitHubIssue(number=783, title="Add onboarding checklist widget", labels=(), state="open"),
                "goose_runner": runner,
                "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
                "repo_path": tmp_path,
            }
        )


def test_spec_node_accepts_clean_spec(tmp_path: Path) -> None:
    # The default FakeRunner writes a clean structured spec — must pass.
    runner = FakeRunner(calls=[])
    result = spec_node(
        {
            "issue": GitHubIssue(number=17, title="Fix mesh discovery", labels=(), state="open"),
            "goose_runner": runner,
            "config": Config(target_repo="atvirokodosprendimai/wgmesh"),
            "repo_path": tmp_path,
        }
    )
    assert result["spec_path"].endswith("issue-17-spec.md")


@pytest.mark.parametrize(
    "marker",
    [
        "goose is ready",
        "● new session ·",
        "Could not parse tool arguments",
        "the response may have been truncated",
        "-32602",
    ],
)
def test_spec_malformed_reason_flags_each_marker(marker: str) -> None:
    assert _spec_malformed_reason(f"# Spec\n\n## Classification\nfeature\n{marker}\n") is not None


def test_spec_malformed_reason_passes_clean_spec() -> None:
    clean = (
        "# Issue #779: Implement Trial Signup Analytics Funnel\n\n"
        "## Classification\nfeature\n\n## Problem Analysis\nThe flow lacks visibility.\n"
    )
    assert _spec_malformed_reason(clean) is None
