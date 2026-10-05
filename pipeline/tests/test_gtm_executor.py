from __future__ import annotations

import pytest

from wgmesh_pipeline.gtm_lane.executor import ItemStatus, execute_item
from wgmesh_pipeline.gtm_lane.fake_provider import FakeProvider
from wgmesh_pipeline.gtm_lane.job_spec import JobSpec, parse_job_spec
from wgmesh_pipeline.gtm_lane.provider import JobResult, ResultState


def _item(item_id: str = "item-1") -> dict:
    return {"id": item_id, "title": "Build competitor pricing sheet", "content": "5 rows"}


def _draft(item) -> JobSpec:
    return JobSpec(
        id=str(item["id"]),
        task="build a 5-row competitor pricing sheet",
        acceptance_criteria=("5 rows", "one column per competitor"),
        safety_bounds=("no PII",),
        job_class="competitor_recon",
    )


# --- characterization: fail-open queue-return (write FIRST) ----------------


def test_draft_failure_requeues_item_unchanged() -> None:
    def boom(_item):
        raise RuntimeError("draft exploded")

    fake = FakeProvider()
    outcome = execute_item(_item(), draft_fn=boom, provider=fake)
    assert outcome.status is ItemStatus.REQUEUED  # fail-open, not raised
    assert fake.dispatch_count == 0  # never dispatched
    assert outcome.item == _item()  # item returned unchanged


def test_dispatch_failure_requeues_item_unchanged() -> None:
    class ExplodingProvider(FakeProvider):
        def dispatch(self, job_spec):
            raise RuntimeError("provider down")

    outcome = execute_item(_item(), draft_fn=_draft, provider=ExplodingProvider())
    assert outcome.status is ItemStatus.REQUEUED
    assert outcome.item == _item()


def test_execute_item_never_raises_on_internal_error() -> None:
    def boom(_item):
        raise ValueError("anything")

    # the lane must never propagate — a queued decision is never lost
    outcome = execute_item(_item(), draft_fn=boom, provider=FakeProvider())
    assert outcome.status is ItemStatus.REQUEUED


# --- happy path -------------------------------------------------------------


def test_completed_result_closes_item() -> None:
    fake = FakeProvider()
    fake.script("item-1", JobResult(state=ResultState.COMPLETED, payload={"rows": 5}, proof="url"))
    outcome = execute_item(_item("item-1"), draft_fn=_draft, provider=fake)
    assert outcome.status is ItemStatus.CLOSED
    assert outcome.result.state is ResultState.COMPLETED


@pytest.mark.parametrize("state", [ResultState.EMPTY, ResultState.PENDING, ResultState.GARBAGE])
def test_non_completed_result_does_not_close(state: ResultState) -> None:
    fake = FakeProvider()
    fake.script("item-1", JobResult(state=state))
    outcome = execute_item(_item("item-1"), draft_fn=_draft, provider=fake)
    assert outcome.status is not ItemStatus.CLOSED  # only verified-complete closes


# --- job_spec parsing -------------------------------------------------------


def test_parse_job_spec_from_json() -> None:
    text = (
        '{"id": "x", "task": "do thing", "acceptance_criteria": ["a", "b"], '
        '"safety_bounds": ["no PII"], "job_class": "data_entry"}'
    )
    spec = parse_job_spec(text)
    assert spec.id == "x"
    assert spec.acceptance_criteria == ("a", "b")
    assert spec.job_class == "data_entry"


def test_parse_job_spec_rejects_empty() -> None:
    with pytest.raises(ValueError):
        parse_job_spec("")
