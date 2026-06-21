from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from wgmesh_pipeline.config import CI_GUARDS_CONTEXT
from wgmesh_pipeline.graph.state import GraphState

log = logging.getLogger(__name__)

# Repo root: .../pipeline/wgmesh_pipeline/graph/nodes/guards.py -> parents[4].
_REPO_ROOT = Path(__file__).resolve().parents[4]
PII_SCRIPT = _REPO_ROOT / "scripts" / "lint" / "check-pii-policy.sh"
EMIT_SANITISE_SCRIPT = _REPO_ROOT / "scripts" / "lint" / "check-llm-emit-sanitise.sh"
GUARD_TIMEOUT_SECONDS = 120


def guards_node(state: GraphState, *, runner=subprocess.run) -> GraphState:
    """#1599 Phase D bot-PR CI: run the path-scoped PII guard and the static
    emit-sanitise guard the standalone Actions workflows skip for ``bot/*`` heads,
    expose ``pii_ok`` / ``emit_sanitise_ok`` to the gate, and post the shared
    ``ci/guards`` required status on the PR head.

    Fail-closed: any guard that errors, times out, or exits non-zero leaves its
    flag ``False`` (never a silent pass), so the gate escalates and the posted
    status is ``failure``.
    """
    next_state = dict(state)
    _visit(next_state, "guards")

    # Mirror review_node's two-path split: the guards run their real subprocess
    # scans + status post only on the live path (a real goose runner AND a real
    # github client). On the synthetic/shadow path there is no PR range to scan,
    # so the guards pass (like review_node deriving tests_passed instead of
    # running go test) — this keeps integration harnesses that drive the merge
    # flow without a live PR from being blocked by a guard that has nothing real
    # to check.
    real_path = (
        next_state.get("goose_runner") is not None
        and next_state.get("github") is not None
    )
    if not real_path:
        next_state["pii_ok"] = True
        next_state["emit_sanitise_ok"] = True
        return next_state

    repo_path = Path(next_state.get("repo_path", "."))
    client = next_state.get("github")
    impl_pr = next_state.get("impl_pr")

    base_sha, head_sha = _resolve_range(client, impl_pr)

    if base_sha and head_sha:
        env = {**os.environ, "BASE_SHA": str(base_sha), "HEAD_SHA": str(head_sha)}
        pii_ok = _run_guard(
            ["bash", str(PII_SCRIPT)], cwd=repo_path, env=env, runner=runner
        )
    else:
        log.error("guards: missing base/head SHA — PII check fails closed")
        pii_ok = False

    emit_sanitise_ok = _run_guard(
        ["bash", str(EMIT_SANITISE_SCRIPT), str(repo_path)],
        cwd=repo_path,
        runner=runner,
    )

    next_state["pii_ok"] = pii_ok
    next_state["emit_sanitise_ok"] = emit_sanitise_ok
    _post_guards_status(next_state, head_sha)
    return next_state


def _resolve_range(client, impl_pr) -> tuple[str | None, str | None]:
    if client is None or impl_pr is None:
        return None, None
    try:
        pr = client.get_pr(int(impl_pr))
    except Exception:
        log.exception("guards: could not resolve PR base/head SHA")
        return None, None
    base_sha = (pr.get("base") or {}).get("sha")
    head_sha = (pr.get("head") or {}).get("sha")
    return base_sha, head_sha


def _run_guard(cmd: list[str], *, cwd: Path, env=None, runner=subprocess.run) -> bool:
    try:
        completed = runner(
            cmd,
            cwd=cwd,
            env=env,
            check=False,
            text=True,
            capture_output=True,
            timeout=GUARD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        log.error("guards: %s timed out — fails closed", cmd[1] if len(cmd) > 1 else cmd)
        return False
    except Exception:
        log.exception("guards: %s errored — fails closed", cmd)
        return False
    if completed.returncode != 0:
        log.warning("guards: %s exited %s", cmd, completed.returncode)
    return completed.returncode == 0


def _post_guards_status(state: GraphState, head_sha: str | None) -> None:
    client = state.get("github")
    if client is None or not head_sha:
        return
    all_ok = (
        bool(state.get("tests_passed"))
        and bool(state.get("sanitise_ok"))
        and bool(state.get("pii_ok"))
        and bool(state.get("emit_sanitise_ok"))
    )
    gh_state = "success" if all_ok else "failure"
    # Static description only — never echo a matched email/secret value to the
    # public status surface.
    description = (
        "all guards green"
        if all_ok
        else f"blocked: {_failed_guards(state)}"
    )
    try:
        client.create_commit_status(
            head_sha,
            context=CI_GUARDS_CONTEXT,
            state=gh_state,
            description=description,
        )
    except PermissionError:
        # spec-only mode disallows the write; the gate still enforces internally.
        log.info("guards: ci/guards status post skipped (mode restricts writes)")
    except Exception:
        # A failed post leaves the required check absent → the PR cannot merge,
        # which is the safe direction. Surface it loudly.
        log.exception("guards: ci/guards status post failed")


def _failed_guards(state: GraphState) -> str:
    failed = []
    if not state.get("tests_passed"):
        failed.append("tests")
    if not state.get("sanitise_ok"):
        failed.append("sanitise")
    if not state.get("pii_ok"):
        failed.append("pii")
    if not state.get("emit_sanitise_ok"):
        failed.append("emit-sanitise")
    return ",".join(failed) or "unknown"


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)
