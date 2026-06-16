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
        closed_issue_titles=(),
        issue_labels={1: ("fn:dev", "needs-triage"), 2: ("needs-human",)},
    )


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
