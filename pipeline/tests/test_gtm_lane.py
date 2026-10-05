from __future__ import annotations

import json
from pathlib import Path

import pytest

from wgmesh_pipeline.gtm_lane.budget import BudgetGate, Envelope
from wgmesh_pipeline.gtm_lane.executor import ItemStatus
from wgmesh_pipeline.gtm_lane.fake_provider import FakeProvider
from wgmesh_pipeline.gtm_lane.job_spec import JobSpec
from wgmesh_pipeline.gtm_lane.lane import GtmLane
from wgmesh_pipeline.gtm_lane.provider import JobResult, ResultState
from wgmesh_pipeline.gtm_lane.safety import SafetyGate
from wgmesh_pipeline.gtm_lane.verify import Verifier


def _lane(provider, *, total=10.0, est=0.5, job_class="competitor_recon", telemetry=None) -> GtmLane:
    def draft(_item) -> JobSpec:
        return JobSpec(id="j1", task="t", acceptance_criteria=("c",), job_class=job_class)

    return GtmLane(
        provider=provider,
        draft_fn=draft,
        safety=SafetyGate(sanitiser=lambda _t: True),
        budget=BudgetGate(envelope=Envelope(total=total), per_job_estimate=est),
        verifier=Verifier(judge=lambda _s, _r: True, sanitiser=lambda _t: True),
        telemetry_path=telemetry,
    )


def test_lane_requires_all_gates() -> None:
    # the assembly must fail loudly if a gate is omitted (no silent None default)
    with pytest.raises(TypeError):
        GtmLane(provider=FakeProvider(), draft_fn=lambda _i: None)  # type: ignore[call-arg]


def test_lane_happy_path_closes_and_records_telemetry(tmp_path: Path) -> None:
    fake = FakeProvider()
    fake.script("j1", JobResult(state=ResultState.COMPLETED, payload="x", proof="p", cost_estimate=0.3))
    state = tmp_path / "gtm-state.json"
    lane = _lane(fake, telemetry=state)
    out = lane.run({"id": "i1"})
    assert out.status is ItemStatus.CLOSED
    assert fake.dispatch_count == 1
    assert json.loads(state.read_text())["counts"]["closed"] == 1


def test_lane_disallowed_class_escalates_not_dispatched() -> None:
    fake = FakeProvider()
    lane = _lane(fake, job_class="cold_outreach")
    out = lane.run({"id": "i1"})
    assert out.status is ItemStatus.ESCALATED
    assert fake.dispatch_count == 0


def test_lane_over_budget_parks() -> None:
    fake = FakeProvider()
    fake.script("j1", JobResult(state=ResultState.COMPLETED, payload="x", proof="p"))
    lane = _lane(fake, total=0.1, est=0.5)
    out = lane.run({"id": "i1"})
    assert out.status is ItemStatus.PARKED
    assert fake.dispatch_count == 0
