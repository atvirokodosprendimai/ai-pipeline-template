from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from requests import HTTPError

from wgmesh_pipeline.graph.state import GraphState


def _status(exc: HTTPError) -> int | None:
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) if resp is not None else None


GIT_TIMEOUT_SECONDS = 120
# Commit identity for the bot-authored spec branch. The freshly cloned wgmesh
# checkout has no git user configured, so commits need an explicit identity.
GIT_AUTHOR_NAME = "wgmesh-pipeline"
GIT_AUTHOR_EMAIL = "wgmesh-pipeline@users.noreply.github.com"


def spec_pr_node(state: GraphState) -> GraphState:
    next_state = dict(state)
    _visit(next_state, "spec_pr")
    if next_state.get("spec_pr") is not None:
        return next_state
    if next_state.get("github") is None:
        return next_state

    issue = next_state["issue"]
    repo_path = Path(next_state.get("repo_path", "."))
    spec_path = Path(next_state["spec_path"])
    spec_rel = _relative_spec_path(spec_path, repo_path)
    branch = str(next_state.get("spec_branch") or f"bot/spec-{issue.number}")
    title = f"spec: Issue #{issue.number} - {issue.title}"

    client = next_state["github"]
    mode = getattr(getattr(client, "config", None), "mode", "shadow")
    if mode != "shadow":
        _prepare_spec_branch(repo_path, branch, spec_rel, title)

    client.push_branch(str(repo_path), branch, spec_pr=True)
    # Idempotent create: a retry after a partial run (PR already opened, then a
    # later step failed) hits 422 "a pull request already exists"; reuse it
    # instead of failing the node forever.
    try:
        result = client.create_pr(
            title=title,
            head=branch,
            base="main",
            body=_spec_pr_body(issue.number, spec_rel),
            spec_pr=True,
        )
        pr_number = _pr_number(result)
    except HTTPError as exc:
        if _status(exc) == 422:
            pr_number = client.find_open_pr_number(branch)
        else:
            raise
    if pr_number is None:
        raise RuntimeError("spec PR creation did not return a PR number")

    # needs-triage may already be gone from a prior partial run -> tolerate 404.
    try:
        client.remove_label(issue.number, "needs-triage", spec_pr=True)
    except HTTPError as exc:
        if _status(exc) != 404:
            raise
    client.add_label(issue.number, "copilot-triaging", spec_pr=True)
    next_state["spec_branch"] = branch
    next_state["spec_pr"] = pr_number
    return next_state


def _prepare_spec_branch(repo_path: Path, branch: str, spec_rel: Path, title: str) -> None:
    if not (repo_path / ".git").exists():
        return
    _git(repo_path, "fetch", "origin", "main", check=False)
    # Local test repos may not have origin/main; production branches from the
    # target repo base so stale spec commits cannot accumulate.
    checkout = _git(repo_path, "checkout", "-B", branch, "origin/main", check=False)
    if checkout.returncode != 0:
        _git(repo_path, "checkout", "-B", branch)
    _git(repo_path, "add", str(spec_rel))
    diff = _git(repo_path, "diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        return
    # Per-commit identity: the freshly cloned wgmesh checkout has no user.name/
    # user.email, so a bare `git commit` fails "Author identity unknown".
    _git(
        repo_path,
        "-c", f"user.name={GIT_AUTHOR_NAME}",
        "-c", f"user.email={GIT_AUTHOR_EMAIL}",
        "commit", "-m", title,
    )


def _git(repo_path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed


def _relative_spec_path(spec_path: Path, repo_path: Path) -> Path:
    if not spec_path.is_absolute():
        return spec_path
    try:
        return spec_path.relative_to(repo_path.resolve())
    except ValueError:
        return spec_path


def _spec_pr_body(issue_number: int, spec_path: Path) -> str:
    return f"Spec for issue #{issue_number}.\n\nSpec file: {spec_path}\n"


def _pr_number(result: Any) -> int | None:
    if isinstance(result, dict) and result.get("number") is not None:
        return int(result["number"])
    payload = getattr(result, "payload", None)
    if isinstance(payload, dict) and payload.get("number") is not None:
        return int(payload["number"])
    return None


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)
