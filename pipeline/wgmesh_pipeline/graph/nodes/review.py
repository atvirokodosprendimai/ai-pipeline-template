from __future__ import annotations

import subprocess
from pathlib import Path

from wgmesh_pipeline.graph.state import GraphState
from wgmesh_pipeline.verification import run_verification


SANITISE_SCRIPT = Path(__file__).resolve().parents[4] / "company" / "scripts" / "sanitise.sh"
SANITISE_TIMEOUT_SECONDS = 120


def review_node(state: GraphState) -> GraphState:
    next_state = dict(state)
    _visit(next_state, "review")
    diff = next_state.get("diff", "")
    next_state["sanitise_ok"] = run_sanitise(diff)
    issue = next_state["issue"]
    real_path = next_state.get("goose_runner") is not None and next_state.get("github") is not None
    if real_path:
        branch = str(next_state.get("impl_branch") or f"bot/impl-{issue.number}")
        verification = run_verification(Path(next_state.get("repo_path", ".")), branch)
        next_state["tests_passed"] = verification["tests_passed"]
        next_state["verification"] = verification
    else:
        next_state["tests_passed"] = _tests_passed(next_state)
    next_state.setdefault("review_findings", [])
    return next_state


def run_sanitise(text: str, *, script: Path = SANITISE_SCRIPT) -> bool:
    try:
        completed = subprocess.run(
            [str(script)],
            input=text,
            text=True,
            capture_output=True,
            check=False,
            timeout=SANITISE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0


def _tests_passed(state: GraphState) -> bool:
    if "tests_passed" in state:
        return bool(state["tests_passed"])
    verification = state.get("verification")
    if isinstance(verification, dict):
        if "tests_passed" in verification:
            return bool(verification["tests_passed"])
        if "passed" in verification:
            return bool(verification["passed"])
    return False


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)
