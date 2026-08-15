"""Budget envelope gate (U6).

Provider spend reports asynchronously, so a synchronous per-job dollar cap is not
implementable (see docs/gtm/provider-feasibility.md + the multi-model-routing
learning). The gate is therefore a **pre-dispatch reservation against a tracked
envelope** plus a **bounded-attempts ceiling**: reserve the per-job estimate
before dispatch, park when it would exceed the envelope or no envelope exists,
and reconcile the actual cost on close.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    """The job's estimate would exceed the remaining envelope (or none exists)."""


class AttemptsExhausted(Exception):
    """The job hit the bounded-attempts ceiling."""


@dataclass
class Envelope:
    total: float
    spent: float = 0.0

    @property
    def remaining(self) -> float:
        return self.total - self.spent


@dataclass
class BudgetGate:
    envelope: Envelope
    per_job_estimate: float
    max_attempts: int = 3
    _attempts: dict[str, int] = field(default_factory=dict)
    _reserved: set[str] = field(default_factory=set)

    def record_attempt(self, job_id: str) -> None:
        """Count one attempt; raise AttemptsExhausted past the ceiling."""
        count = self._attempts.get(job_id, 0)
        if count >= self.max_attempts:
            raise AttemptsExhausted(f"{job_id}: {count} attempts >= ceiling {self.max_attempts}")
        self._attempts[job_id] = count + 1

    def reserve(self, job_id: str) -> None:
        """Reserve the per-job estimate against the envelope, ONCE per job. A
        retry of an already-reserved job is a no-op — the estimate is held until
        the job closes (reconcile) or is abandoned (release). Raise BudgetExceeded
        (reserving nothing) when it would overspend."""
        if job_id in self._reserved:
            return  # already holding this job's reservation; do not double-reserve
        if self.per_job_estimate > self.envelope.remaining:
            raise BudgetExceeded(
                f"{job_id}: estimate {self.per_job_estimate} > remaining {self.envelope.remaining}"
            )
        self.envelope.spent += self.per_job_estimate
        self._reserved.add(job_id)

    def reconcile(self, job_id: str, *, actual: float) -> None:
        """On close, replace the held reservation with the actual cost the provider
        reported. No-op if the job was never reserved."""
        if job_id not in self._reserved:
            return
        self.envelope.spent += actual - self.per_job_estimate
        self._reserved.discard(job_id)

    def release(self, job_id: str) -> None:
        """Abandon a job's reservation (parked/escalated and not re-attempted),
        returning the held estimate to the envelope."""
        if job_id in self._reserved:
            self.envelope.spent -= self.per_job_estimate
            self._reserved.discard(job_id)
