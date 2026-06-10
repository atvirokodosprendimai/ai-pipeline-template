from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from requests import HTTPError

from wgmesh_pipeline.config import DEFAULT_RECIPES_DIR
from wgmesh_pipeline.graph.state import GraphState
from wgmesh_pipeline.graph.nodes.spec_pr import GIT_AUTHOR_EMAIL, GIT_AUTHOR_NAME, _git


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
    real_path = runner is not None and next_state.get("github") is not None
    issue = next_state["issue"]
    branch = str(next_state.get("impl_branch") or f"bot/impl-{issue.number}")
    diff_rel = Path("pipeline-output") / f"issue-{next_state['issue'].number}.diff"
    spec_rel = Path("pipeline-output") / f"issue-{issue.number}-spec.md"
    if real_path:
        _materialize_spec(repo_path, next_state, spec_rel)
        _prepare_impl_workspace(repo_path, branch)
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
                "spec_file": str(spec_rel if real_path else next_state["spec_path"]),
                "diff_file": str(diff_rel),
            },
            expected_output=diff_rel,
            stage="implement",
            tier=tier,
            session_id=f"issue-{issue.number}",
        )
        if not result.ok:
            raise RuntimeError(result.error or "goose implementation failed")
        if result.model_key is not None:
            next_state["implement_model_key"] = result.model_key
        if real_path:
            _stage_impl_tree(repo_path)
            if _git(repo_path, "diff", "--cached", "--quiet", check=False).returncode == 0:
                raise RuntimeError("goose implementation produced no tree changes")
            next_state["diff"] = _git(repo_path, "diff", "--cached").stdout
            _git(
                repo_path,
                "-c", f"user.name={GIT_AUTHOR_NAME}",
                "-c", f"user.email={GIT_AUTHOR_EMAIL}",
                "commit", "-m", f"impl: Issue #{issue.number} - {issue.title}",
            )
        else:
            next_state["diff"] = Path(result.output_path).read_text()
    else:
        next_state["diff"] = "+docs-only change\n"
    next_state["changed_files"] = changed_files_from_diff(next_state["diff"])
    if real_path:
        next_state["github"].push_branch(str(repo_path), branch)
        next_state["impl_branch"] = branch
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


def _materialize_spec(repo_path: Path, state: dict, spec_rel: Path) -> None:
    issue_number = state["issue"].number
    content: str | None = None
    fetched = _git(repo_path, "fetch", "origin", f"bot/spec-{issue_number}", check=False)
    if fetched.returncode == 0:
        shown = _git(repo_path, "show", f"FETCH_HEAD:specs/issue-{issue_number}-spec.md", check=False)
        if shown.returncode == 0:
            content = shown.stdout
    if content is None:
        current_spec = repo_path / str(state["spec_path"])
        if current_spec.exists():
            content = current_spec.read_text()
    if content is None:
        raise RuntimeError("spec file unavailable for implement")
    spec_path = repo_path / spec_rel
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(content)


def _prepare_impl_workspace(repo_path: Path, branch: str) -> None:
    _git(repo_path, "fetch", "origin", "main", check=False)
    checkout = _git(repo_path, "checkout", "-B", branch, "origin/main", check=False)
    if checkout.returncode != 0:
        _git(repo_path, "checkout", "-B", branch)
    _git(repo_path, "checkout", "--", ".")
    # go-cache: goose's model has improvised GOMODCACHE=go-cache inside the
    # checkout; Go module caches are write-protected, so git clean dies on
    # them (live incident 2026-06-10 18:29Z). Exclude rather than fight.
    _git(repo_path, "clean", "-fd", "--exclude=pipeline-output", "--exclude=go-cache")


def _stage_impl_tree(repo_path: Path) -> None:
    _git(repo_path, "add", "-A")
    _git(repo_path, "reset", "-q", "--", "pipeline-output")


def _ensure_impl_pr(state: dict) -> None:
    if state.get("impl_pr") is not None or state.get("github") is None:
        return
    issue = state["issue"]
    branch = str(state.get("impl_branch") or f"bot/impl-{issue.number}")
    try:
        result = state["github"].create_pr(
            title=f"fix: Issue #{issue.number} - {issue.title}",
            head=branch,
            base="main",
            body=_impl_pr_body(issue.number, state.get("changed_files", [])),
        )
        pr_number = _pr_number(result)
    except HTTPError as exc:
        if _status(exc) == 422 and "already exists" in str(exc).lower():
            pr_number = state["github"].find_open_pr_number(branch)
        else:
            raise
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


def _status(exc: HTTPError) -> int | None:
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) if resp is not None else None


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)
