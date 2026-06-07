from __future__ import annotations

from pathlib import Path

from wgmesh_pipeline.graph.state import GraphState


def spec_node(state: GraphState) -> GraphState:
    next_state = dict(state)
    _visit(next_state, "spec")
    if next_state.get("spec_path"):
        return next_state

    issue = next_state["issue"]
    repo_path = Path(next_state.get("repo_path", "."))
    spec_rel = Path("specs") / f"issue-{issue.number}-spec.md"
    runner = next_state.get("goose_runner")
    if runner is None:
        next_state["spec_path"] = str(spec_rel)
        return next_state

    result = runner.run_recipe(
        recipe="wgmesh-triage-spec.yaml",
        workdir=repo_path,
        params={"spec_file": str(spec_rel)},
        expected_output=spec_rel,
    )
    if not result.ok:
        raise RuntimeError(result.error or "goose spec failed")
    next_state["spec_path"] = str(result.output_path)
    return next_state


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)

