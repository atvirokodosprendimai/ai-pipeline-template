"""Vendor-agnostic rented-human provider adapter (U2).

The lane targets this dispatch+verify contract, not a specific vendor, so the
U1-chosen provider (Toloka by default) wires in behind the seam without lane
rework. ``FakeProvider`` (see ``fake_provider``) backs the tests so U3-U9 build
without a live, funded account.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


class ResultState(enum.Enum):
    """The four states a fetched result may be in. Never coerce to COMPLETED —
    the verifier (U5) must see EMPTY/GARBAGE/PENDING distinctly so a silent zero
    is not graded as done."""

    COMPLETED = "completed"
    EMPTY = "empty"
    GARBAGE = "garbage"
    PENDING = "pending"


@dataclass(frozen=True)
class JobResult:
    """A fetched result. ``proof`` is the structured completion artifact the U5
    verifier checks against the dispatched job (Toloka assignment JSON /
    Microworkers screenshot URL / HumanOps photo)."""

    state: ResultState
    payload: Any = None
    proof: Any = None
    worker_meta: Mapping[str, Any] = field(default_factory=dict)
    cost_estimate: float | None = None


@runtime_checkable
class HumanTaskProvider(Protocol):
    """A rented-human task provider.

    IDEMPOTENCY IS A HARD CONTRACT: ``dispatch`` MUST dedupe on the payload's
    ``idempotency_key`` (== the job id). The lane requeues and re-dispatches the
    SAME job when ``fetch_result`` raises (network/provider error), so a
    non-idempotent adapter would create a second *paid* task on every fetch
    failure. A real adapter that cannot dedupe server-side must persist its own
    job-id→handle map and short-circuit a repeat dispatch.
    """

    def dispatch(self, job_spec: Mapping[str, Any]) -> str:
        """Submit one task (deduping on ``job_spec['idempotency_key']``); return an
        opaque provider handle."""
        ...

    def fetch_result(self, handle: str) -> JobResult:
        """Retrieve the result for a previously dispatched handle."""
        ...


def provider_env(allow: set[str], *, source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a provider subprocess env from an **allowlist** (fail-closed).

    Only keys named in ``allow`` are passed; everything else is dropped. A denylist
    would be fail-open and miss new secrets (see the multi-model-routing learning).
    A required key absent from ``source`` raises ``KeyError`` rather than silently
    starting an under-credentialed provider.
    """
    src = os.environ if source is None else source
    out: dict[str, str] = {}
    for key in allow:
        if key not in src:
            raise KeyError(f"required provider credential {key!r} not in environment")
        out[key] = src[key]
    return out
