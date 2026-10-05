"""Recipe-backed job-spec drafter (U3).

Mirrors ``decision_lane/proposal_runner.build_proposal_fn``: multi-line content
(the brief, the GTM playbook) is handed to the recipe as temp-file paths, never
inline params. Returns a ``draft_fn(item) -> JobSpec`` the executor calls. The
``learnings_file`` param is grounded via the shipped ``write_learnings_file``
seam over the vendored GTM corpus in ``docs/solutions/gtm-playbook/`` (U7).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from wgmesh_pipeline.config import DEFAULT_RECIPES_DIR, Config
from wgmesh_pipeline.goose.runner import GooseRunner
from wgmesh_pipeline.gtm_lane.job_spec import JobSpec, parse_job_spec
from wgmesh_pipeline.learnings import write_learnings_file

log = logging.getLogger("wgmesh_pipeline.gtm_lane.draft")


def build_draft_fn(config: Config) -> Callable[[Mapping[str, Any]], JobSpec]:
    runner = GooseRunner(config)
    recipes_dir = Path(getattr(config, "recipes_dir", DEFAULT_RECIPES_DIR))
    recipe = recipes_dir / "wgmesh-gtm-job-draft.yaml"
    strategy = str(Path(config.repo_path) / "STRATEGY.md")

    def _draft(item: Mapping[str, Any]) -> JobSpec:
        title = str(item.get("title", ""))
        brief = str(item.get("content") or "")
        brief_file = ""
        if brief.strip():
            fd, brief_file = tempfile.mkstemp(prefix="gtm-brief-", suffix=".md")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(brief)
        # Ground the draft in the vendored GTM playbook (docs/solutions/gtm-playbook
        # via the shipped learnings seam), keyed on the decision text. Fail-open:
        # an empty/error result yields an empty path the recipe branches on. The
        # corpus lives in docs/solutions/; the lane emits jobs to pipeline-output/,
        # so there is no self-ingestion of the lane's own output.
        learnings_file = write_learnings_file(
            f"{title}\n{brief}", prefix=f"gtm-{item.get('id', 'x')}-learnings-"
        )
        out_rel = Path("pipeline-output") / f"gtm-job-{item.get('id', 'x')}.json"
        try:
            result = runner.run_recipe(
                recipe=recipe,
                workdir=Path(config.repo_path),
                params={
                    "item_title": title,
                    "brief_file": brief_file,
                    "strategy_file": strategy,
                    "learnings_file": learnings_file,
                    "job_spec_file": str(out_rel),
                },
                expected_output=out_rel,
                stage="gtm_draft",
                session_id=f"gtm-{item.get('id', 'x')}",
            )
            out_path = Path(config.repo_path) / out_rel
            if not result.ok or not out_path.exists():
                raise RuntimeError(f"gtm job-draft produced no output for {title!r}")
            return parse_job_spec(out_path.read_text(encoding="utf-8"))
        finally:
            for tmp in (brief_file, learnings_file):
                if tmp:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

    return _draft
