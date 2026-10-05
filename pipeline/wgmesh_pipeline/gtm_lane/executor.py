"""GTM-execution lane core (U3).

Orchestrates one approved low-risk item end-to-end: draft a job spec → dispatch
to the rented-human provider → ingest the result → close (or requeue/escalate).

Fail-open: ANY internal error returns the item to the queue in its prior state.
A queued decision is never lost, dropped, or double-dispatched. The safety gate
(U4), verification gate (U5), and budget gate (U6) are layered into this flow in
their own units.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from wgmesh_pipeline.gtm_lane.job_spec import JobSpec
from wgmesh_pipeline.gtm_lane.provider import HumanTaskProvider, JobResult, ResultState
from wgmesh_pipeline.gtm_lane.budget import AttemptsExhausted, BudgetExceeded, BudgetGate
from wgmesh_pipeline.gtm_lane.safety import SafetyGate, SafetyRejection
from wgmesh_pipeline.gtm_lane.verify import Verifier, VerifyOutcome

log = logging.getLogger("wgmesh_pipeline.gtm_lane.executor")


class ItemStatus(enum.Enum):
    CLOSED = "closed"
    REQUEUED = "requeued"  # fail-open: returned to queue in prior state
    ESCALATED = "escalated"  # safety/hard-verify rejected → needs-human, never dispatched
    PARKED = "parked"  # over budget / attempts exhausted → park + notify cofounder


@dataclass(frozen=True)
class ItemOutcome:
    status: ItemStatus
    item: Mapping[str, Any]
    job_spec: JobSpec | None = None
    result: JobResult | None = None
    reason: str = ""


DraftFn = Callable[[Mapping[str, Any]], JobSpec]

_VERDICT_TO_STATUS = {
    VerifyOutcome.PASS: ItemStatus.CLOSED,
    VerifyOutcome.RETRY: ItemStatus.REQUEUED,
    VerifyOutcome.ESCALATE: ItemStatus.ESCALATED,
}


def execute_item(
    item: Mapping[str, Any],
    *,
    draft_fn: DraftFn,
    provider: HumanTaskProvider,
    safety: SafetyGate | None = None,
    budget: BudgetGate | None = None,
    verifier: Verifier | None = None,
) -> ItemOutcome:
    """Run one item through draft → safety gate → dispatch → ingest → verify →
    close. Never raises: any failure yields a REQUEUED outcome carrying the item
    unchanged. Safety rejection or a hard verify failure yields ESCALATED.

    ``safety``/``verifier`` are optional only to keep lower-layer tests focused;
    the production lane assembly always supplies both."""
    try:
        job_spec = draft_fn(item)
        if safety is not None:
            try:
                safety.check(job_spec)
            except SafetyRejection as rej:
                log.info("gtm safety gate rejected item %s: %s", item.get("id"), rej)
                return ItemOutcome(
                    status=ItemStatus.ESCALATED, item=item, job_spec=job_spec, reason=str(rej)
                )
        if budget is not None:
            try:
                budget.record_attempt(job_spec.id)
                budget.reserve(job_spec.id)
            except (BudgetExceeded, AttemptsExhausted) as exc:
                log.info("gtm budget gate parked item %s: %s", item.get("id"), exc)
                budget.release(job_spec.id)  # abandon any held reservation from prior attempts
                return ItemOutcome(
                    status=ItemStatus.PARKED, item=item, job_spec=job_spec, reason=str(exc)
                )
        handle = provider.dispatch(_dispatch_payload(job_spec))
        result = provider.fetch_result(handle)
        if verifier is not None:
            verdict = verifier.verify(job_spec, result)
            # Default unmapped verdicts to ESCALATED (fail-closed): never let a new
            # VerifyOutcome silently fall through the fail-open except into a retry.
            status = _VERDICT_TO_STATUS.get(verdict.outcome, ItemStatus.ESCALATED)
            reason = verdict.reason
        elif result.state is ResultState.COMPLETED:
            # No verifier (lower-layer tests only): COMPLETED closes, else requeue.
            status, reason = ItemStatus.CLOSED, ""
        else:
            status, reason = ItemStatus.REQUEUED, f"result not completed: {result.state.value}"
        _settle_budget(budget, job_spec.id, status, result)
        return ItemOutcome(status=status, item=item, job_spec=job_spec, result=result, reason=reason)
    except Exception as exc:  # noqa: BLE001 — fail-open; a queued decision is never lost
        log.warning("gtm lane error for item %s; requeuing", item.get("id"), exc_info=True)
        return ItemOutcome(status=ItemStatus.REQUEUED, item=item, reason=str(exc))


def _settle_budget(
    budget: BudgetGate | None, job_id: str, status: ItemStatus, result: JobResult | None
) -> None:
    """Settle the held reservation after the outcome is known. CLOSED reconciles
    to the provider's reported cost (when present); a terminal non-retry outcome
    releases the held estimate; REQUEUED keeps it (the retry re-uses it)."""
    if budget is None:
        return
    if status is ItemStatus.CLOSED:
        actual = getattr(result, "cost_estimate", None)
        if actual is not None:
            budget.reconcile(job_id, actual=actual)
    elif status in (ItemStatus.ESCALATED, ItemStatus.PARKED):
        budget.release(job_id)


def _dispatch_payload(job_spec: JobSpec) -> dict[str, Any]:
    return {
        "id": job_spec.id,
        "idempotency_key": job_spec.id,  # real adapters MUST dedupe on this — a
        # fetch_result failure requeues and re-dispatches the same job (see
        # provider.HumanTaskProvider contract).
        "task": job_spec.task,
        "acceptance_criteria": list(job_spec.acceptance_criteria),
        "safety_bounds": list(job_spec.safety_bounds),
        "payload": dict(job_spec.payload),
    }
