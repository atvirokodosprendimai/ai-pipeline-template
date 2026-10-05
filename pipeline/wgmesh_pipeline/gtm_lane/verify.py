"""Fail-closed verification gate (U5).

Mirrors the impl-judge discipline: a deliverable is graded only when it is
actually present. Fail-closed gates fire BEFORE the LLM judge so an empty or
absent result can never be scored as "done" (the langfuse-empty-output failure
class). Security reasons (a secret in the returned artifact) and empty/absent
work escalate straight to needs-human; only a quality shortfall retries.
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass
from typing import Callable

from wgmesh_pipeline.gtm_lane.job_spec import JobSpec
from wgmesh_pipeline.gtm_lane.provider import JobResult, ResultState
from wgmesh_pipeline.gtm_lane.safety import Sanitiser

log = logging.getLogger("wgmesh_pipeline.gtm_lane.verify")


class VerifyOutcome(enum.Enum):
    PASS = "pass"          # verified complete → close
    RETRY = "retry"        # quality shortfall or still pending → bounded retry
    ESCALATE = "escalate"  # empty/absent/garbage/security → needs-human, never retried


@dataclass(frozen=True)
class VerifyVerdict:
    outcome: VerifyOutcome
    reason: str = ""


# judge(job_spec, result) -> True when the returned work satisfies the acceptance
# criteria. A judge that raises or returns non-True is treated as a quality fail.
Judge = Callable[[JobSpec, JobResult], bool]


@dataclass
class Verifier:
    judge: Judge
    sanitiser: Sanitiser

    def verify(self, job_spec: JobSpec, result: JobResult) -> VerifyVerdict:
        # 1. State gate (fail-closed): only COMPLETED is gradable.
        if result.state is ResultState.PENDING:
            return VerifyVerdict(VerifyOutcome.RETRY, "result still pending")
        if result.state is not ResultState.COMPLETED:
            return VerifyVerdict(VerifyOutcome.ESCALATE, f"result state {result.state.value}")

        # 2. Presence gate (fail-closed): empty work / absent proof can never pass.
        if not _nonempty(result.payload):
            return VerifyVerdict(VerifyOutcome.ESCALATE, "returned work is empty")
        if not _nonempty(result.proof):
            return VerifyVerdict(VerifyOutcome.ESCALATE, "completion proof absent")

        # 3. Security gate: a secret in the returned artifact escalates, never retries.
        if not self.sanitiser(_artifact_text(result)):
            return VerifyVerdict(VerifyOutcome.ESCALATE, "returned artifact failed sanitise")

        # 4. Quality judge (last, on real content). Raise/non-True → quality fail.
        try:
            passed = bool(self.judge(job_spec, result))
        except Exception:  # noqa: BLE001 — a judge error is a fail, never a pass
            log.warning("gtm verify judge errored for %s; treating as quality fail", job_spec.id, exc_info=True)
            passed = False
        if passed:
            return VerifyVerdict(VerifyOutcome.PASS, "verified complete")
        return VerifyVerdict(VerifyOutcome.RETRY, "judge: acceptance criteria not met")


def _nonempty(value: object) -> bool:
    # "Is there work?" — None, empty containers/strings, AND falsy scalars
    # (0, 0.0, False = a count-of-zero deliverable) all count as no work.
    return bool(value)


def _artifact_text(result: JobResult) -> str:
    return json.dumps({"payload": result.payload, "proof": result.proof}, default=str)
