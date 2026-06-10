from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from wgmesh_pipeline.config import DEFAULT_RECIPES_DIR
from wgmesh_pipeline.graph.state import GraphState


def implement_node(state: GraphState) -> GraphState:
    next_state = dict(state)
    _visit(next_state, "implement")
    tier = int(next_state.get("escalation_tier", 0))
    if next_state.get("diff") and tier == 0:
        next_state["changed_files"] = changed_files_from_diff(next_state["diff"])
        _ensure_impl_pr(next_state)
        return next_state

    runner = next_state.get("goose_runner")
    repo_path = Path(next_state.get("repo_path", "."))
    diff_rel = Path("pipeline-output") / f"issue-{next_state['issue'].number}.diff"
    if runner is not None:
        # Resolve against the pipeline's recipes dir (mirrors spec_node): goose
        # runs with cwd=repo_path (the wgmesh clone), where a bare recipe name
        # does not exist — that was the live-mode 'goose exited 1' on every
        # implement attempt.
        config = next_state.get("config")
        recipes_dir = Path(getattr(config, "recipes_dir", DEFAULT_RECIPES_DIR))
        result = runner.run_recipe(
            recipe=recipes_dir / "wgmesh-implementation.yaml",
            workdir=repo_path,
            # diff_file mirrors expected_output: the recipe instructs goose to
            # write the unified diff there, the runner verifies it appeared.
            params={
                "spec_file": str(next_state["spec_path"]),
                "diff_file": str(diff_rel),
            },
            expected_output=diff_rel,
            stage="implement",
            tier=tier,
        )
        if not result.ok:
            raise RuntimeError(result.error or "goose implementation failed")
        if result.model_key is not None:
            next_state["implement_model_key"] = result.model_key
        next_state["diff"] = Path(result.output_path).read_text()
    else:
        next_state["diff"] = "+docs-only change\n"
    next_state["changed_files"] = changed_files_from_diff(next_state["diff"])
    _ensure_impl_pr(next_state)
    if tier > 0:
        _note_escalation_on_pr(next_state, tier)
    return next_state


def _note_escalation_on_pr(state: dict, tier: int) -> None:
    """On a retry pass, annotate the EXISTING impl PR with the escalated tier
    rather than opening a second PR (R5). The body text is static (no LLM
    content), but update_pr_body still routes through the sanitise gate."""
    client = state.get("github")
    impl_pr = state.get("impl_pr")
    if client is None or impl_pr is None:
        return
    model = state.get("implement_model_key") or f"tier {tier}"
    issue_number = state["issue"].number
    body = _impl_pr_body(issue_number, state.get("changed_files", []))
    body += f"\nEscalated to model `{model}` (tier {tier}) after a quality-gate failure.\n"
    client.update_pr_body(int(impl_pr), body)


def changed_files_from_diff(diff: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        path = _path_from_git_header(line) or _path_from_plus_header(line)
        if path and path not in seen:
            seen.add(path)
            files.append(path)
    return files


def _path_from_git_header(line: str) -> str | None:
    match = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
    if not match:
        return None
    return _normalise_diff_path(match.group(2))


def _path_from_plus_header(line: str) -> str | None:
    if not line.startswith("+++ "):
        return None
    return _normalise_diff_path(line[4:].strip())


def _normalise_diff_path(path: str) -> str | None:
    if path == "/dev/null":
        return None
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _ensure_impl_pr(state: dict) -> None:
    if state.get("impl_pr") is not None or state.get("github") is None:
        return
    issue = state["issue"]
    result = state["github"].create_pr(
        title=f"fix: Issue #{issue.number} - {issue.title}",
        head=f"bot/impl-{issue.number}",
        base="main",
        body=_impl_pr_body(issue.number, state.get("changed_files", [])),
    )
    pr_number = _pr_number(result)
    if pr_number is None:
        raise RuntimeError("implementation PR creation did not return a PR number")
    state["impl_pr"] = pr_number


def _impl_pr_body(issue_number: int, changed_files: list[str]) -> str:
    files = "\n".join(f"- {path}" for path in changed_files) or "- no changed files detected"
    return f"Implementation for issue #{issue_number}.\n\nChanged files:\n{files}\n"


def _pr_number(result: Any) -> int | None:
    if isinstance(result, dict) and result.get("number") is not None:
        return int(result["number"])
    payload = getattr(result, "payload", None)
    if isinstance(payload, dict) and payload.get("number") is not None:
        return int(payload["number"])
    return None


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)
