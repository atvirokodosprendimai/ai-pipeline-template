"""Job spec model + parser (U3). The job-draft step (recipe) emits a JSON job
spec; the executor parses it into this structured form. The low-risk job-class
allowlist is added in U4."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


# Low-risk job classes the MVP lane will dispatch to a rented human (U4). Anything
# outside this set — especially outbound contact as the company — stays in the
# needs-human queue until the dispatch+verify loop is proven.
LOW_RISK_CLASSES: frozenset[str] = frozenset(
    {
        "lead_research",
        "list_building",
        "manual_signup",
        "content_qa",
        "competitor_recon",
        "data_entry",
    }
)


@dataclass(frozen=True)
class JobSpec:
    id: str
    task: str
    acceptance_criteria: tuple[str, ...]
    safety_bounds: tuple[str, ...] = ()
    job_class: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)


def _as_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def parse_job_spec(text: str) -> JobSpec:
    """Parse a JSON job spec emitted by the draft recipe. Raises ``ValueError``
    on empty/malformed input (fail-closed — the executor must not dispatch a
    blank job)."""
    if not text or not text.strip():
        raise ValueError("empty job spec")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed job spec: {exc}") from exc
    if not isinstance(data, dict) or not data.get("id") or not data.get("task"):
        raise ValueError("job spec missing required id/task")
    return JobSpec(
        id=str(data["id"]),
        task=str(data["task"]),
        acceptance_criteria=_as_tuple(data.get("acceptance_criteria")),
        safety_bounds=_as_tuple(data.get("safety_bounds")),
        job_class=str(data.get("job_class", "")),
        payload=data.get("payload") or {},
    )
