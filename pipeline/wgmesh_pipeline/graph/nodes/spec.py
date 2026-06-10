from __future__ import annotations

import logging
from pathlib import Path

from wgmesh_pipeline.config import DEFAULT_RECIPES_DIR
from wgmesh_pipeline.graph.state import GraphState

log = logging.getLogger("wgmesh_pipeline.spec")


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

    config = next_state.get("config")
    recipes_dir = Path(getattr(config, "recipes_dir", DEFAULT_RECIPES_DIR))
    recipe_path = recipes_dir / "wgmesh-triage-spec.yaml"
    result = runner.run_recipe(
        recipe=recipe_path,
        workdir=repo_path,
        params={
            "issue_number": str(issue.number),
            "issue_title": issue.title,
            "spec_file": str(spec_rel),
        },
        expected_output=spec_rel,
        stage="spec",
        session_id=f"issue-{issue.number}",
    )
    if not result.ok:
        # Surface goose's actual output so a write-tool/model/recipe failure is
        # diagnosable from the journal instead of just "empty output guard".
        raw = getattr(result, "raw_log", "") or ""
        # Log head AND tail: the provider/API error appears at the START of
        # goose's output; the tail-only view missed it last cycle.
        head = raw[:6000]
        tail = raw[-2000:] if len(raw) > 8000 else ""
        log.error(
            "goose spec failed for #%s: error=%s recipe=%s workdir=%s len(raw)=%d\n"
            "--- goose raw_log (head) ---\n%s\n--- goose raw_log (tail) ---\n%s",
            issue.number, result.error, recipe_path, repo_path, len(raw), head, tail,
        )
        raise RuntimeError(result.error or "goose spec failed")
    next_state["spec_path"] = str(result.output_path)
    if result.model_key is not None:
        next_state["spec_model_key"] = result.model_key
    # Put the authored spec text into state so trace_node includes it in the
    # "spec" span output — this is what a managed Langfuse LLM-as-a-Judge reads
    # to score spec quality. Capped + best-effort (a read failure must not break
    # the loop). Traced to private Langfuse only; never committed from here.
    next_state["spec_content"] = _read_excerpt(result.output_path)
    return next_state


_SPEC_EXCERPT_LIMIT = 6000


def _read_excerpt(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:_SPEC_EXCERPT_LIMIT]
    except Exception:
        return ""


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)
