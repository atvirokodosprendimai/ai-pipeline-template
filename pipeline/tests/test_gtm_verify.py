from __future__ import annotations

import pytest

from wgmesh_pipeline.gtm_lane.executor import ItemStatus, execute_item
from wgmesh_pipeline.gtm_lane.fake_provider import FakeProvider
from wgmesh_pipeline.gtm_lane.job_spec import JobSpec
from wgmesh_pipeline.gtm_lane.provider import JobResult, ResultState
from wgmesh_pipeline.gtm_lane.verify import VerifyOutcome, Verifier


def _spec() -> JobSpec:
    return JobSpec(id="j1", task="build a 5-row sheet", acceptance_criteria=("5 rows",), job_class="competitor_recon")


def _completed(payload="5 rows of data", proof="sheet-url") -> JobResult:
    return JobResult(state=ResultState.COMPLETED, payload=payload, proof=proof)


_CLEAN = lambda _t: True  # noqa: E731
_PASS_JUDGE = lambda _s, _r: True  # noqa: E731
_FAIL_JUDGE = lambda _s, _r: False  # noqa: E731


# --- fail-closed gates fire BEFORE the judge --------------------------------


def test_completed_proof_and_judge_pass_is_pass() -> None:  # AE1
    v = Verifier(judge=_PASS_JUDGE, sanitiser=_CLEAN)
    assert v.verify(_spec(), _completed()).outcome is VerifyOutcome.PASS


def test_quality_fail_when_judge_rejects() -> None:  # AE4
    v = Verifier(judge=_FAIL_JUDGE, sanitiser=_CLEAN)
    assert v.verify(_spec(), _completed()).outcome is VerifyOutcome.RETRY


def test_empty_payload_escalates_without_consulting_judge() -> None:
    consulted = []

    def judge(_s, _r):
        consulted.append(1)
        return True

    v = Verifier(judge=judge, sanitiser=_CLEAN)
    out = v.verify(_spec(), _completed(payload="")).outcome
    assert out is VerifyOutcome.ESCALATE  # fail-closed on empty
    assert not consulted  # judge never reached


def test_absent_proof_escalates() -> None:
    v = Verifier(judge=_PASS_JUDGE, sanitiser=_CLEAN)
    assert v.verify(_spec(), _completed(proof=None)).outcome is VerifyOutcome.ESCALATE


@pytest.mark.parametrize("state", [ResultState.EMPTY, ResultState.GARBAGE])
def test_empty_or_garbage_state_escalates(state: ResultState) -> None:
    v = Verifier(judge=_PASS_JUDGE, sanitiser=_CLEAN)
    assert v.verify(_spec(), JobResult(state=state)).outcome is VerifyOutcome.ESCALATE


def test_pending_state_retries() -> None:
    v = Verifier(judge=_PASS_JUDGE, sanitiser=_CLEAN)
    assert v.verify(_spec(), JobResult(state=ResultState.PENDING)).outcome is VerifyOutcome.RETRY


def test_returned_artifact_tripping_sanitise_escalates() -> None:
    # a secret in the returned work is a security reason → straight to escalate
    v = Verifier(judge=_PASS_JUDGE, sanitiser=lambda _t: False)
    assert v.verify(_spec(), _completed()).outcome is VerifyOutcome.ESCALATE


def test_judge_raising_is_fail_closed() -> None:
    def boom(_s, _r):
        raise RuntimeError("judge error")

    v = Verifier(judge=boom, sanitiser=_CLEAN)
    # a judge error must not pass — fail-closed to retry, never silent close
    assert v.verify(_spec(), _completed()).outcome is not VerifyOutcome.PASS


# --- executor integration: ladder maps outcomes to item status -------------


def test_executor_pass_closes() -> None:
    fake = FakeProvider()
    fake.script("j1", _completed())
    v = Verifier(judge=_PASS_JUDGE, sanitiser=_CLEAN)
    outcome = execute_item({"id": "i1"}, draft_fn=lambda _i: _spec(), provider=fake, verifier=v)
    assert outcome.status is ItemStatus.CLOSED


def test_executor_quality_fail_requeues() -> None:
    fake = FakeProvider()
    fake.script("j1", _completed())
    v = Verifier(judge=_FAIL_JUDGE, sanitiser=_CLEAN)
    outcome = execute_item({"id": "i1"}, draft_fn=lambda _i: _spec(), provider=fake, verifier=v)
    assert outcome.status is ItemStatus.REQUEUED


def test_executor_empty_escalates() -> None:
    fake = FakeProvider()
    fake.script("j1", _completed(payload=""))
    v = Verifier(judge=_PASS_JUDGE, sanitiser=_CLEAN)
    outcome = execute_item({"id": "i1"}, draft_fn=lambda _i: _spec(), provider=fake, verifier=v)
    assert outcome.status is ItemStatus.ESCALATED
