from __future__ import annotations

import logging
import os
import tempfile
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
    # The brief (PM body) is multi-line, so it can NOT be inlined as a recipe
    # param — goose substitutes params into the YAML before parsing and a
    # multi-line value breaks the `prompt: |` scalar. Hand it over as a FILE
    # path (the same convention as spec_file / open_board_file); empty body →
    # empty path → the recipe falls back to the title.
    brief = str(next_state.get("issue_body", "") or "")
    brief_file = ""
    if brief.strip():
        fd, brief_file = tempfile.mkstemp(
            prefix=f"issue-{issue.number}-brief-", suffix=".md"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(brief)
    try:
        result = runner.run_recipe(
            recipe=recipe_path,
            workdir=repo_path,
            params={
                "issue_number": str(issue.number),
                "issue_title": issue.title,
                "issue_brief_file": brief_file,
                "spec_file": str(spec_rel),
            },
            expected_output=spec_rel,
            stage="spec",
            session_id=f"issue-{issue.number}",
        )
    finally:
        if brief_file:
            try:
                os.unlink(brief_file)
            except OSError:
                pass
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
    # Content gate: result.ok only proves the spec file exists and is non-empty.
    # On #783, goose dumped a 3672-line session transcript whose final write-tool
    # call was truncated ("-32602: Could not parse tool arguments") — a malformed
    # "spec" that passed result.ok, advanced to implement, and produced off-spec
    # code the judge then rejected. Reject a transcript/truncated spec here so it
    # fails like any other spec failure (retry/escalate) instead of poisoning the
    # downstream impl.
    reason = _spec_malformed_reason(_read_full(result.output_path))
    if reason:
        log.error("malformed spec for #%s: %s", issue.number, reason)
        raise RuntimeError(f"malformed spec: {reason}")
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
# Capacious enough to scan a bloated transcript head+tail without reading an
# unbounded file; the discriminating markers appear at the start (goose banner)
# and end (truncated-write error) of a transcript-spec.
_SPEC_SCAN_LIMIT = 500_000

# Markers that appear in a goose session TRANSCRIPT or a truncated write-tool
# call, and never in a clean authored spec (verified: #783 has all of these,
# clean spec #779 has none). Their presence means the spec write failed and the
# file captured the raw session instead of a structured spec.
_MALFORMED_MARKERS = (
    "goose is ready",
    "● new session ·",
    "Could not parse tool arguments",
    "the response may have been truncated",
    "-32602",
)


def _spec_malformed_reason(content: str) -> str | None:
    """Return a reason string if the spec content is a goose transcript or a
    truncated write rather than a clean spec, else None."""
    for marker in _MALFORMED_MARKERS:
        if marker in content:
            return (
                f"spec file contains goose-transcript/error marker {marker!r} — "
                "the spec write likely truncated, leaving a raw session instead "
                "of a structured spec"
            )
    return None


def _read_full(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:_SPEC_SCAN_LIMIT]
    except Exception:
        return ""


def _read_excerpt(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:_SPEC_EXCERPT_LIMIT]
    except Exception:
        return ""


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)
