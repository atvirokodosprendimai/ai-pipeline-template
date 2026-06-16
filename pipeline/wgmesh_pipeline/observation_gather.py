"""Live input gather for the box-side observation loop.

This module owns the impure half that ``observation.py`` deliberately avoids:
forge reads for the issue snapshot, an on-box Goose assessment call, defensive
JSON parsing, and executor routing. Any LLM failure or unparseable assessment is
a loud skip with zero fabricated actions.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.control_loop.executor import ExecutionResult, execute_actions
from wgmesh_pipeline.forge.protocol import Forge
from wgmesh_pipeline.goose.runner import GooseRunner
from wgmesh_pipeline.observation import ObservationInputs, ObservationPlan, plan_actions

log = logging.getLogger("wgmesh_pipeline.observation_gather")

ASSESSMENT_KEYS = ("issues_to_create", "issues_to_close", "needs_human", "prs_to_close")


class ObservationAssessor(Protocol):
    def __call__(self, inputs: ObservationInputs) -> Mapping[str, Any] | str: ...


ObservationPlanner = Callable[[Mapping[str, Any], ObservationInputs], ObservationPlan]
ObservationExecutor = Callable[[Forge, Any, Sequence[Any]], list[ExecutionResult]]


@dataclass(frozen=True)
class ObservationCycleResult:
    inputs: ObservationInputs | None
    assessment: Mapping[str, Any]
    plan: ObservationPlan | None
    execution_results: tuple[ExecutionResult, ...]
    skipped: bool
    skip_reason: str | None = None


def build_observation_inputs(forge: Forge) -> ObservationInputs:
    """Build planner inputs from the forge's open issue snapshot.

    ``closed_issue_titles`` degrades to ``()`` because the current forge
    protocol has no closed-issue listing. The close guard still fails closed on
    missing labels; this only narrows duplicate detection until the protocol
    grows a closed-title read.
    """
    issues = [
        issue
        for issue in forge.list_open_issues()
        if not getattr(issue, "pull_request", None)
    ]
    return ObservationInputs(
        open_issue_titles=tuple(str(issue.title) for issue in issues),
        closed_issue_titles=(),
        issue_labels={
            int(issue.number): tuple(str(label) for label in issue.labels)
            for issue in issues
        },
    )


def parse_assessment(payload: Mapping[str, Any] | str) -> dict[str, Any] | None:
    if isinstance(payload, Mapping):
        raw: Any = dict(payload)
    elif isinstance(payload, str):
        try:
            raw = json.loads(_strip_json_fence(payload))
        except json.JSONDecodeError:
            return None
    else:
        return None
    if not isinstance(raw, Mapping):
        return None
    assessment: dict[str, Any] = {}
    for key in ASSESSMENT_KEYS:
        value = raw.get(key, [])
        if value is None:
            value = []
        if not isinstance(value, list):
            return None
        assessment[key] = value
    return assessment


def run_observation_cycle(
    forge: Forge,
    store: Any,
    *,
    assessor: ObservationAssessor,
    planner: ObservationPlanner = plan_actions,
    executor: ObservationExecutor = execute_actions,
) -> ObservationCycleResult:
    try:
        inputs = build_observation_inputs(forge)
    except Exception as exc:  # noqa: BLE001 - required input, loud skip
        log.warning(
            "control_loop: module=observation skipped: forge input gather failed: %s",
            exc,
        )
        return ObservationCycleResult(
            None, {}, None, (), True, "forge input gather failed"
        )

    try:
        parsed = parse_assessment(assessor(inputs))
    except Exception as exc:  # noqa: BLE001 - LLM unreachable, loud skip
        log.warning(
            "control_loop: module=observation skipped: LLM assessment failed: %s", exc
        )
        return ObservationCycleResult(
            inputs, {}, None, (), True, "LLM assessment failed"
        )
    if parsed is None:
        log.warning(
            "control_loop: module=observation skipped: LLM assessment was not strict JSON"
        )
        return ObservationCycleResult(
            inputs, {}, None, (), True, "LLM assessment was not strict JSON"
        )

    try:
        plan = planner(parsed, inputs)
    except Exception as exc:  # noqa: BLE001 - bad model item, no partial writes
        log.warning(
            "control_loop: module=observation skipped: assessment planning failed: %s",
            exc,
        )
        return ObservationCycleResult(
            inputs, parsed, None, (), True, "assessment planning failed"
        )
    results = tuple(executor(forge, store, plan.actions))
    statuses = [result.status for result in results]
    log.info(
        "control_loop: module=observation planned_actions=%s skips=%s executed=%s result_statuses=%s",
        len(plan.actions),
        len(plan.skips),
        sum(1 for status in statuses if status == "executed"),
        statuses[:5],
    )
    return ObservationCycleResult(inputs, parsed, plan, results, False)


@dataclass(frozen=True)
class GooseObservationAssessor:
    """On-box observation assessment via the same Goose runner path used by
    ``graph.nodes.implement``. The recipe is generated in a temp directory so
    this U4 unit does not add a new permanent recipe file."""

    config: Config
    repo_root: Path

    def __call__(self, inputs: ObservationInputs) -> Mapping[str, Any]:
        with tempfile.TemporaryDirectory(prefix="wgmesh-observation-") as tmp:
            tmp_path = Path(tmp)
            output = tmp_path / "assessment.json"
            recipe = tmp_path / "observation-assessment.yaml"
            recipe.write_text(_assessment_recipe(), encoding="utf-8")
            result = GooseRunner(self.config).run_recipe(
                recipe=recipe,
                workdir=self.repo_root,
                params={
                    "assessment_file": str(output),
                    "open_board": _inputs_board(inputs),
                },
                expected_output=output,
                stage="observation",
                session_id="control-loop-observation",
            )
            if not result.ok or result.output_path is None:
                # Surface the raw goose output (head+tail) — otherwise a goose
                # startup/config failure is invisible (only "goose exited N"
                # reaches the log), which left the box's observation loop dark
                # with no way to tell why. (observability-cracks lesson.)
                raw = result.raw_log or ""
                log.warning(
                    "control_loop: observation goose failed (%s) — raw_log "
                    "head:\n%s\n--- tail:\n%s",
                    result.error,
                    raw[:1500],
                    raw[-1500:],
                )
                raise RuntimeError(
                    result.error or "goose observation assessment failed"
                )
            parsed = parse_assessment(result.output_path.read_text(encoding="utf-8"))
            if parsed is None:
                raise ValueError("goose observation assessment was not strict JSON")
            return parsed


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _inputs_board(inputs: ObservationInputs) -> str:
    lines = ["## Open Issues (wgmesh)", ""]
    for number, title in enumerate(inputs.open_issue_titles, start=1):
        lines.append(f"- {number}. {title}")
    if not inputs.open_issue_titles:
        lines.append("- (none)")
    return "\n".join(lines)


def _assessment_recipe() -> str:
    return """version: "1.0.0"
title: "wgmesh Observation Assessment"
description: "Assess current company signals and emit strict JSON actions."
parameters:
  - key: assessment_file
    input_type: string
    requirement: required
    description: "Absolute path where strict JSON assessment must be written."
  - key: open_board
    input_type: string
    requirement: required
    description: "Open issue board snapshot."
prompt: |
  You are the observation loop for wgmesh, a decentralized WireGuard mesh
  networking product with managed ingress.

  Current open board:
  {{ open_board }}

  Write ONLY strict JSON to this exact file path:
  {{ assessment_file }}

  The JSON object MUST contain exactly these four keys, each an array:
  - issues_to_create: objects with title, body, labels
  - issues_to_close: objects with number, reason
  - needs_human: objects with request, urgency, reason
  - prs_to_close: objects with repo, number, reason

  If no action is justified, write empty arrays. Never include secrets,
  customer PII, or exact revenue figures.
extensions:
  - type: builtin
    name: developer
    display_name: Developer
    timeout: 300
    bundled: true
settings:
  goose_provider: anthropic
  goose_model: GLM-5.2
"""
