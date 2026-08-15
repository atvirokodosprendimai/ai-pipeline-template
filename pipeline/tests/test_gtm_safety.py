from __future__ import annotations

import pytest

from wgmesh_pipeline.gtm_lane.executor import ItemStatus, execute_item
from wgmesh_pipeline.gtm_lane.fake_provider import FakeProvider
from wgmesh_pipeline.gtm_lane.job_spec import JobSpec
from wgmesh_pipeline.gtm_lane.provider import JobResult, ResultState
from wgmesh_pipeline.gtm_lane.safety import (
    SafetyGate,
    SafetyRejection,
    run_sanitise,
)

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
SANITISE = REPO_ROOT / "company" / "scripts" / "sanitise.sh"


def _spec(job_class: str = "competitor_recon", task: str = "build a 5-row sheet") -> JobSpec:
    return JobSpec(id="j1", task=task, acceptance_criteria=("5 rows",), job_class=job_class)


# --- job-class allowlist ----------------------------------------------------


@pytest.mark.parametrize(
    "cls", ["lead_research", "list_building", "manual_signup", "content_qa", "competitor_recon", "data_entry"]
)
def test_allowlisted_classes_pass(cls: str) -> None:
    SafetyGate(sanitiser=lambda _t: True).check(_spec(job_class=cls))  # no raise


def test_non_allowlisted_class_rejected() -> None:
    with pytest.raises(SafetyRejection):
        SafetyGate(sanitiser=lambda _t: True).check(_spec(job_class="pricing_negotiation"))


def test_outbound_class_rejected() -> None:
    with pytest.raises(SafetyRejection):
        SafetyGate(sanitiser=lambda _t: True).check(_spec(job_class="cold_outreach"))


# --- sanitise wall (real script, both directions) ---------------------------


def test_sanitise_rejects_secret() -> None:
    # a Stripe live-key pattern must trip the wall. Assembled at runtime so the
    # literal never lands in source (GitHub push protection flags the contiguous
    # token even as a test fixture).
    secret = "sk_" + "live_" + "a" * 24
    assert run_sanitise(f"token {secret}", script=SANITISE) is False


def test_sanitise_allows_clean_text_with_bare_key_word() -> None:
    # narrow scoping: the bare word "key" in prose must NOT be flagged
    assert run_sanitise("press any key to continue, no secrets here", script=SANITISE) is True


def test_gate_rejects_spec_carrying_secret() -> None:
    gate = SafetyGate(sanitiser=lambda t: run_sanitise(t, script=SANITISE))
    token = "ghp" + "_" + "0" * 36  # GitHub-PAT pattern, assembled at runtime
    bad = JobSpec(id="j1", task=f"use {token}", acceptance_criteria=(), job_class="data_entry")
    with pytest.raises(SafetyRejection):
        gate.check(bad)


# --- executor integration: disallowed class escalates, never dispatches -----


def test_disallowed_job_escalates_not_dispatched() -> None:
    fake = FakeProvider()
    fake.script("item-1", JobResult(state=ResultState.COMPLETED, payload={"x": 1}, proof="p"))
    gate = SafetyGate(sanitiser=lambda _t: True)

    def draft(_item) -> JobSpec:
        return _spec(job_class="cold_outreach")  # outbound-as-company

    outcome = execute_item({"id": "item-1"}, draft_fn=draft, provider=fake, safety=gate)
    assert outcome.status is ItemStatus.ESCALATED
    assert fake.dispatch_count == 0  # never dispatched


def test_allowed_job_with_gate_still_dispatches_and_closes() -> None:
    fake = FakeProvider()
    # the fake keys results by the dispatched job_spec.id ("j1"), not the item id
    fake.script("j1", JobResult(state=ResultState.COMPLETED, payload={"x": 1}, proof="p"))
    gate = SafetyGate(sanitiser=lambda _t: True)
    outcome = execute_item({"id": "item-1"}, draft_fn=lambda _i: _spec(), provider=fake, safety=gate)
    assert outcome.status is ItemStatus.CLOSED
    assert fake.dispatch_count == 1
