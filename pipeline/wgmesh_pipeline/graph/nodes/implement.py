from __future__ import annotations

from pathlib import Path

from wgmesh_pipeline.graph.state import GraphState


def implement_node(state: GraphState) -> GraphState:
    next_state = dict(state)
    _visit(next_state, "implement")
    if next_state.get("diff"):
        next_state.setdefault("changed_files", ["docs/implementation.md"])
        return next_state

    runner = next_state.get("goose_runner")
    repo_path = Path(next_state.get("repo_path", "."))
    diff_rel = Path("pipeline-output") / f"issue-{next_state['issue'].number}.diff"
    if runner is not None:
        result = runner.run_recipe(
            recipe="wgmesh-implementation.yaml",
            workdir=repo_path,
            params={"spec_file": str(next_state["spec_path"])},
            expected_output=diff_rel,
        )
        if not result.ok:
            raise RuntimeError(result.error or "goose implementation failed")
        next_state["diff"] = Path(result.output_path).read_text()
    else:
        next_state["diff"] = "+docs-only change\n"
    next_state.setdefault("changed_files", ["docs/implementation.md"])
    return next_state


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)

