from __future__ import annotations

import pytest

from wgmesh_pipeline.gtm_lane.provider import (
    JobResult,
    ResultState,
    provider_env,
)
from wgmesh_pipeline.gtm_lane.fake_provider import FakeProvider


def _job(job_id: str = "job-1") -> dict:
    return {"id": job_id, "task": "build a 5-row competitor sheet", "payload": {}}


def test_dispatch_returns_handle_then_fetch_completed() -> None:
    fake = FakeProvider()
    fake.script("job-1", JobResult(state=ResultState.COMPLETED, payload={"rows": 5}, proof="sheet-url"))
    handle = fake.dispatch(_job("job-1"))
    assert handle
    result = fake.fetch_result(handle)
    assert result.state is ResultState.COMPLETED
    assert result.payload == {"rows": 5}
    assert result.proof == "sheet-url"


@pytest.mark.parametrize(
    "state",
    [ResultState.EMPTY, ResultState.GARBAGE, ResultState.PENDING],
)
def test_non_completed_states_reported_distinctly(state: ResultState) -> None:
    fake = FakeProvider()
    fake.script("job-1", JobResult(state=state))
    handle = fake.dispatch(_job("job-1"))
    result = fake.fetch_result(handle)
    assert result.state is state  # no coercion to COMPLETED
    if state is not ResultState.COMPLETED:
        assert not result.payload


def test_dispatch_is_idempotent_on_job_id() -> None:
    fake = FakeProvider()
    h1 = fake.dispatch(_job("job-1"))
    h2 = fake.dispatch(_job("job-1"))  # same id → same handle, no double dispatch
    assert h1 == h2
    assert fake.dispatch_count == 1


def test_provider_env_allowlist_passes_named_keys() -> None:
    src = {"TOLOKA_TOKEN": "t", "SECRET_OTHER": "x", "PATH": "/bin"}
    env = provider_env({"TOLOKA_TOKEN"}, source=src)
    assert env == {"TOLOKA_TOKEN": "t"}  # allowlist: only named keys, fail-closed


def test_provider_env_missing_required_key_raises() -> None:
    with pytest.raises(KeyError):
        provider_env({"TOLOKA_TOKEN"}, source={"PATH": "/bin"})
