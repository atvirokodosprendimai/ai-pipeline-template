from __future__ import annotations

import subprocess
from pathlib import Path

from wgmesh_pipeline.graph.state import GraphState


SANITISE_SCRIPT = Path(__file__).resolve().parents[4] / "company" / "scripts" / "sanitise.sh"


def review_node(state: GraphState) -> GraphState:
    next_state = dict(state)
    _visit(next_state, "review")
    diff = next_state.get("diff", "")
    next_state["sanitise_ok"] = run_sanitise(diff)
    next_state.setdefault("tests_passed", True)
    next_state.setdefault("review_findings", [])
    return next_state


def run_sanitise(text: str, *, script: Path = SANITISE_SCRIPT) -> bool:
    completed = subprocess.run(
        [str(script)],
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)
