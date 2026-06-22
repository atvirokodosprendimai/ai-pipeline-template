from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from wgmesh_pipeline.observation import (
    ObservationAction,
    ObservationInputs,
    ObservationPlan,
)
from wgmesh_pipeline.observation_gather import (
    build_observation_inputs,
    run_observation_cycle,
)


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    labels: tuple[str, ...]
    state: str = "open"
    pull_request: dict[str, Any] | None = None


class ShadowForge:
    def __init__(self) -> None:
        self.write_calls: list[tuple[str, Any]] = []

    def list_open_issues(self) -> list[Issue]:
        return [
            Issue(1, "Ship CLI onboarding", ("fn:dev", "needs-triage")),
            Issue(2, "Blocked deploy", ("needs-human",)),
        ]

    def create_issue(self, **kwargs: Any) -> dict[str, Any]:
        self.write_calls.append(("create_issue", kwargs))
        return {"dry_run": True, "operation": "create_issue"}


class RaisingWriteForge(ShadowForge):
    def create_issue(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("real forge write reached")


class Store:
    pass


def test_build_observation_inputs_from_open_issue_snapshot() -> None:
    inputs = build_observation_inputs(ShadowForge())

    assert inputs == ObservationInputs(
        open_issue_titles=("Ship CLI onboarding", "Blocked deploy"),
        open_issue_numbers=(1, 2),
        closed_issue_titles=(),
        issue_labels={1: ("fn:dev", "needs-triage"), 2: ("needs-human",)},
    )


def test_inputs_board_shows_real_issue_numbers() -> None:
    # The board the LLM sees must carry REAL numbers (#726), not sequence
    # indices — its close/needs-human proposals reference these, and a sequence
    # index fails the close guard (issue_labels is keyed by real number).
    from wgmesh_pipeline.observation_gather import _inputs_board

    board = _inputs_board(
        ObservationInputs(
            open_issue_titles=("Stuck deploy", "VPN start/stop"),
            open_issue_numbers=(727, 539),
        )
    )
    assert "- #727: Stuck deploy" in board
    assert "- #539: VPN start/stop" in board


def test_observation_cycle_logs_skip_detail_codes(caplog) -> None:
    # A vetoed cycle must surface WHY (code#number), so a 0-action cycle is not
    # mistaken for the LLM declining.
    from wgmesh_pipeline.observation import ObservationSkip

    def planner(
        assessment: Mapping[str, Any], inputs: ObservationInputs
    ) -> ObservationPlan:
        return ObservationPlan(
            actions=(),
            skips=(
                ObservationSkip(
                    action="close_issue",
                    code="label_fetch_failed",
                    message="x",
                    number=42,
                ),
            ),
        )

    with caplog.at_level(logging.INFO, logger="wgmesh_pipeline.observation_gather"):
        run_observation_cycle(
            ShadowForge(),
            Store(),
            assessor=lambda _inputs: {"issues_to_close": [{"number": 42}]},
            planner=planner,
        )
    assert "label_fetch_failed#42" in caplog.text


def test_valid_llm_assessment_plans_and_executes_shadow_dry_run(caplog) -> None:
    forge = ShadowForge()
    planned_inputs: list[ObservationInputs] = []

    def assessor(inputs: ObservationInputs) -> Mapping[str, Any]:
        assert inputs.open_issue_titles == ("Ship CLI onboarding", "Blocked deploy")
        return {
            "issues_to_create": [{"title": "Add smoke test", "body": "b", "labels": []}]
        }

    def planner(
        assessment: Mapping[str, Any], inputs: ObservationInputs
    ) -> ObservationPlan:
        planned_inputs.append(inputs)
        assert assessment["issues_to_create"][0]["title"] == "Add smoke test"
        return ObservationPlan(
            actions=(
                ObservationAction(
                    kind="create_issue", title="Add smoke test", body="b"
                ),
            ),
            skips=(),
        )

    with caplog.at_level(logging.INFO, logger="wgmesh_pipeline.observation_gather"):
        result = run_observation_cycle(
            forge, Store(), assessor=assessor, planner=planner
        )

    assert planned_inputs
    assert result.skipped is False
    assert result.assessment["issues_to_create"][0]["title"] == "Add smoke test"
    assert [r.status for r in result.execution_results] == ["executed"]
    assert forge.write_calls == [
        ("create_issue", {"title": "Add smoke test", "body": "b", "labels": ()})
    ]
    assert "module=observation" in caplog.text


@pytest.mark.parametrize(
    "bad_assessor",
    [
        lambda _inputs: (_ for _ in ()).throw(RuntimeError("llm down")),
        lambda _inputs: "not json",
    ],
)
def test_llm_failure_or_junk_loud_skips_without_fabricating_or_writing(
    bad_assessor: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    planner_calls = 0

    def planner(
        assessment: Mapping[str, Any], inputs: ObservationInputs
    ) -> ObservationPlan:
        nonlocal planner_calls
        planner_calls += 1
        return ObservationPlan(actions=(), skips=())

    with caplog.at_level(logging.WARNING, logger="wgmesh_pipeline.observation_gather"):
        result = run_observation_cycle(
            RaisingWriteForge(),
            Store(),
            assessor=bad_assessor,
            planner=planner,
        )

    assert result.skipped is True
    assert result.assessment == {}
    assert planner_calls == 0
    assert result.execution_results == ()
    assert "skipped" in caplog.text


def test_goose_assessor_surfaces_raw_log_on_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # A goose startup/config failure must surface its raw stdout/stderr, not
    # just "goose exited N" — otherwise the box's observation loop goes dark
    # with no diagnosable reason (the bug that hid why the live flip produced
    # zero work). Reverting the raw_log log makes this RED.
    from pathlib import Path

    from wgmesh_pipeline import observation_gather as og
    from wgmesh_pipeline.config import Config

    class _FailResult:
        ok = False
        output_path = None
        raw_log = "GOOSE-RAW: provider config invalid; could not start"
        error = "goose exited 1"

    class _FakeRunner:
        def __init__(self, config: Config) -> None:
            self.config = config

        def run_recipe(self, **kwargs: Any) -> _FailResult:
            return _FailResult()

    monkeypatch.setattr(og, "GooseRunner", _FakeRunner)
    assessor = og.GooseObservationAssessor(
        config=Config(target_repo="atvirokodosprendimai/wgmesh"),
        repo_root=Path("."),
    )
    with caplog.at_level(logging.WARNING, logger="wgmesh_pipeline.observation_gather"):
        with pytest.raises(RuntimeError):
            assessor(ObservationInputs())
    assert "GOOSE-RAW: provider config invalid" in caplog.text


def test_assessment_recipe_templates_params_as_single_line_paths() -> None:
    # goose substitutes {{ params }} into the recipe text BEFORE parsing it, so
    # every param must be a single-line value (a path) — a multi-line value
    # injected into the `prompt: |` block breaks out of the literal scalar and
    # goose rejects the recipe ("Invalid recipe: did not find expected key").
    # Regression for the live observation flip producing zero work. (No PyYAML
    # dep — assert the path-not-content contract directly.)
    from wgmesh_pipeline.observation_gather import _assessment_recipe

    recipe = _assessment_recipe()
    assert "{{ open_board_file }}" in recipe
    assert "{{ strategy_file }}" in recipe  # goal-aware, not just board
    assert "{{ open_board }}" not in recipe  # never inline the multi-line board
    # Customer-acquisition steering (approved 2026-06-17): the loop proposes
    # paid-customer growth work, not housekeeping.
    assert "PAID CUSTOMERS" in recipe
    assert "lead-capture form" in recipe  # pre-wires the nurture/Mautic handoff


def test_assessment_recipe_requires_pm_grade_body_sections() -> None:
    # The post body becomes the builder's brief (cutover follow-on), so the
    # assess loop must emit a structured PM-grade feature description, not a
    # one-liner. Assert the prompt demands each section by its exact heading.
    from wgmesh_pipeline.observation_gather import _assessment_recipe

    recipe = _assessment_recipe()
    for heading in (
        "## Problem",
        "## Proposed Solution",
        "## Pros",
        "## Cons",
        "## ROI / Impact",
        "## Acceptance Criteria",
    ):
        assert heading in recipe, f"assess prompt must require body section {heading!r}"
    # Templating a param must not add lines (single-line path values only).
    templated = (
        recipe.replace("{{ open_board_file }}", "/tmp/board.md")
        .replace("{{ assessment_file }}", "/tmp/assessment.json")
        .replace("{{ strategy_file }}", "/tmp/STRATEGY.md")
    )
    assert recipe.count("\n") == templated.count("\n")
