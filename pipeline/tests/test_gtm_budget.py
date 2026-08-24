from __future__ import annotations

import pytest

from wgmesh_pipeline.gtm_lane.budget import (
    AttemptsExhausted,
    BudgetExceeded,
    BudgetGate,
    Envelope,
)
from wgmesh_pipeline.gtm_lane.executor import ItemStatus, execute_item
from wgmesh_pipeline.gtm_lane.fake_provider import FakeProvider
from wgmesh_pipeline.gtm_lane.job_spec import JobSpec
from wgmesh_pipeline.gtm_lane.provider import JobResult, ResultState


def _spec() -> JobSpec:
    return JobSpec(id="j1", task="t", acceptance_criteria=("c",), job_class="data_entry")


def _gate(total=10.0, est=0.5, max_attempts=3) -> BudgetGate:
    return BudgetGate(envelope=Envelope(total=total, spent=0.0), per_job_estimate=est, max_attempts=max_attempts)


# --- reservation ------------------------------------------------------------


def test_within_envelope_reserves_and_spends() -> None:
    gate = _gate(total=10.0, est=0.5)
    gate.reserve("j1")
    assert gate.envelope.spent == pytest.approx(0.5)
    assert gate.envelope.remaining == pytest.approx(9.5)


def test_over_envelope_raises() -> None:  # AE3
    gate = _gate(total=0.3, est=0.5)
    with pytest.raises(BudgetExceeded):
        gate.reserve("j1")
    assert gate.envelope.spent == 0.0  # nothing reserved on rejection


def test_no_envelope_raises() -> None:
    gate = _gate(total=0.0, est=0.5)
    with pytest.raises(BudgetExceeded):
        gate.reserve("j1")


def test_reconcile_adjusts_spend_on_close() -> None:
    gate = _gate(total=10.0, est=0.5)
    gate.reserve("j1")  # reserved 0.5
    gate.reconcile("j1", actual=0.3)  # actual cheaper
    assert gate.envelope.spent == pytest.approx(0.3)


def test_reserve_is_idempotent_per_job() -> None:
    # a retry of the same job must NOT double-reserve (the drain-3x cascade)
    gate = _gate(total=10.0, est=0.5)
    gate.reserve("j1")
    gate.reserve("j1")
    gate.reserve("j1")
    assert gate.envelope.spent == pytest.approx(0.5)  # held once


def test_release_returns_held_estimate() -> None:
    gate = _gate(total=10.0, est=0.5)
    gate.reserve("j1")
    gate.release("j1")
    assert gate.envelope.spent == pytest.approx(0.0)
    # after release the job can reserve again
    gate.reserve("j1")
    assert gate.envelope.spent == pytest.approx(0.5)


# --- bounded attempts -------------------------------------------------------


def test_attempts_ceiling_exhausts() -> None:
    gate = _gate(max_attempts=2)
    gate.record_attempt("j1")
    gate.record_attempt("j1")
    with pytest.raises(AttemptsExhausted):
        gate.record_attempt("j1")


# --- executor integration ---------------------------------------------------


def test_over_budget_parks_not_dispatched() -> None:  # AE3
    fake = FakeProvider()
    fake.script("j1", JobResult(state=ResultState.COMPLETED, payload="ok", proof="p"))
    gate = _gate(total=0.1, est=0.5)
    outcome = execute_item({"id": "i1"}, draft_fn=lambda _i: _spec(), provider=fake, budget=gate)
    assert outcome.status is ItemStatus.PARKED
    assert fake.dispatch_count == 0


def test_within_budget_dispatches() -> None:
    fake = FakeProvider()
    fake.script("j1", JobResult(state=ResultState.COMPLETED, payload="ok", proof="p"))
    gate = _gate(total=10.0, est=0.5)
    outcome = execute_item({"id": "i1"}, draft_fn=lambda _i: _spec(), provider=fake, budget=gate)
    assert outcome.status is ItemStatus.CLOSED
    assert fake.dispatch_count == 1
    assert gate.envelope.spent == pytest.approx(0.5)


def test_retrying_item_does_not_double_spend() -> None:
    # verify RETRY → REQUEUED; re-running the same item must hold ONE reservation,
    # not accumulate per attempt (the drain cascade the review flagged)
    from wgmesh_pipeline.gtm_lane.verify import Verifier

    fake = FakeProvider()
    fake.script("j1", JobResult(state=ResultState.COMPLETED, payload="x", proof="p"))
    v = Verifier(judge=lambda _s, _r: False, sanitiser=lambda _t: True)  # always RETRY
    gate = _gate(total=10.0, est=0.5, max_attempts=5)
    for _ in range(3):
        out = execute_item({"id": "i1"}, draft_fn=lambda _i: _spec(), provider=fake, budget=gate, verifier=v)
        assert out.status is ItemStatus.REQUEUED
    assert gate.envelope.spent == pytest.approx(0.5)  # one reservation across retries


def test_escalated_item_releases_reservation() -> None:
    from wgmesh_pipeline.gtm_lane.verify import Verifier

    fake = FakeProvider()
    fake.script("j1", JobResult(state=ResultState.COMPLETED, payload="", proof="p"))  # empty → ESCALATE
    v = Verifier(judge=lambda _s, _r: True, sanitiser=lambda _t: True)
    gate = _gate(total=10.0, est=0.5)
    out = execute_item({"id": "i1"}, draft_fn=lambda _i: _spec(), provider=fake, budget=gate, verifier=v)
    assert out.status is ItemStatus.ESCALATED
    assert gate.envelope.spent == pytest.approx(0.0)  # reservation released, not stranded


def test_closed_reconciles_to_reported_cost() -> None:
    from wgmesh_pipeline.gtm_lane.verify import Verifier

    fake = FakeProvider()
    fake.script("j1", JobResult(state=ResultState.COMPLETED, payload="x", proof="p", cost_estimate=0.2))
    v = Verifier(judge=lambda _s, _r: True, sanitiser=lambda _t: True)
    gate = _gate(total=10.0, est=0.5)
    out = execute_item({"id": "i1"}, draft_fn=lambda _i: _spec(), provider=fake, budget=gate, verifier=v)
    assert out.status is ItemStatus.CLOSED
    assert gate.envelope.spent == pytest.approx(0.2)  # reconciled estimate→actual


def test_attempts_exhausted_parks() -> None:
    fake = FakeProvider()
    fake.script("j1", JobResult(state=ResultState.COMPLETED, payload="ok", proof="p"))
    gate = _gate(total=10.0, est=0.5, max_attempts=1)
    gate.record_attempt("j1")  # pre-exhaust
    outcome = execute_item({"id": "i1"}, draft_fn=lambda _i: _spec(), provider=fake, budget=gate)
    assert outcome.status is ItemStatus.PARKED
    assert fake.dispatch_count == 0
