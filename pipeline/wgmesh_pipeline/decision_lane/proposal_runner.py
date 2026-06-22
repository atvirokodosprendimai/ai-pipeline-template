"""Live proposal generator (U7) — runs the decision-proposal recipe via Goose.

Only exercised in LIVE mode (shadow never calls ``proposal_fn``). Mirrors the
spec node's file-path convention: multi-line content (the brief, the prior
proposal, the feedback) is handed to the recipe as temp-file paths, never inline
params (the YAML-scalar trap). Internal grounding only — STRATEGY.md + the post
body; no web research (Phase 2).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from wgmesh_pipeline.config import DEFAULT_RECIPES_DIR, Config
from wgmesh_pipeline.goose.runner import GooseRunner

log = logging.getLogger("wgmesh_pipeline.decision_lane.proposal")


def build_proposal_fn(
    config: Config,
) -> Callable[[dict[str, Any], dict[str, Any] | None], str]:
    """Return a ``proposal_fn(post, latest_comment) -> markdown`` backed by the
    Goose recipe. The returned text is the proposal to post as a comment."""
    runner = GooseRunner(config)
    recipes_dir = Path(getattr(config, "recipes_dir", DEFAULT_RECIPES_DIR))
    recipe = recipes_dir / "wgmesh-decision-proposal.yaml"
    strategy = str(Path(config.repo_path) / "STRATEGY.md")

    def _proposal(post: dict[str, Any], latest_comment: dict[str, Any] | None) -> str:
        title = str(post.get("title", ""))
        brief = str(post.get("content") or "")
        tmps: list[str] = []

        def _tmp(text: str, suffix: str) -> str:
            if not text.strip():
                return ""
            fd, path = tempfile.mkstemp(prefix="decision-", suffix=suffix)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            tmps.append(path)
            return path

        brief_file = _tmp(brief, "-brief.md")
        feedback_file = _tmp(
            str((latest_comment or {}).get("content") or ""), "-feedback.md"
        )
        out_rel = Path("specs") / f"decision-{post.get('id','x')}-proposal.md"
        try:
            result = runner.run_recipe(
                recipe=recipe,
                workdir=Path(config.repo_path),
                params={
                    "decision_title": title,
                    "brief_file": brief_file,
                    "strategy_file": strategy,
                    "prior_proposal_file": "",  # Phase 1: stateless re-draft
                    "feedback_file": feedback_file,
                    "proposal_file": str(out_rel),
                },
                expected_output=out_rel,
                stage="decision",
                session_id=f"decision-{post.get('id','x')}",
            )
            out_path = Path(config.repo_path) / out_rel
            if not result.ok or not out_path.exists():
                raise RuntimeError(
                    f"decision proposal recipe produced no output for {title!r}"
                )
            return out_path.read_text(encoding="utf-8")
        finally:
            for path in tmps:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    return _proposal
