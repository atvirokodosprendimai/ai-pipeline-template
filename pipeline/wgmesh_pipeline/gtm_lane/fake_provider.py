"""In-memory fake provider (U2) for deterministic lane tests.

Scripts a JobResult per job id so U3-U9 exercise every result state
(completed-with-proof / empty / garbage / pending) without a live, funded vendor.
Idempotent on the job id: re-dispatching the same job returns the same handle and
does not double-dispatch.
"""

from __future__ import annotations

from typing import Any, Mapping

from wgmesh_pipeline.gtm_lane.provider import JobResult, ResultState


class FakeProvider:
    def __init__(self) -> None:
        self._scripted: dict[str, JobResult] = {}
        self._handles: dict[str, str] = {}  # job_id -> handle
        self.dispatch_count = 0

    def script(self, job_id: str, result: JobResult) -> None:
        """Pre-load the result a future fetch should return for ``job_id``."""
        self._scripted[job_id] = result

    def dispatch(self, job_spec: Mapping[str, Any]) -> str:
        job_id = str(job_spec["id"])
        if job_id in self._handles:  # idempotent — no double dispatch
            return self._handles[job_id]
        handle = f"fake-handle-{job_id}"
        self._handles[job_id] = handle
        self.dispatch_count += 1
        return handle

    def fetch_result(self, handle: str) -> JobResult:
        job_id = handle.removeprefix("fake-handle-")
        # default to PENDING when nothing scripted — never a silent "done"
        return self._scripted.get(job_id, JobResult(state=ResultState.PENDING))
