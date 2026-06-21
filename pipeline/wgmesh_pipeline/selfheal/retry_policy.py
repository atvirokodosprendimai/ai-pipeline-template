"""Shared retry-gate policy (cooldown → cap → escalate).

Extracted from the stale-sweep engine (``sweeps.py::_sweep_stale``) so the
conflict-heal planner reuses the *exact* cooldown/cap/escalate-at-N semantics
without duplicating them. Pure: no I/O, returns a new ``Decision``.

The existing sweeps are intentionally left calling their inline copy to protect
the byte-exact parity test; consolidating them onto this helper is deferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from wgmesh_pipeline.selfheal.models import shift


@dataclass(frozen=True)
class Decision:
    """Outcome of the retry gate for one tracked item.

    ``kind`` is one of ``"skip"`` (cooling down), ``"act"`` (below the cap,
    attempt the heal), or ``"escalate"`` (cap reached). ``cooldown_until`` is
    populated only when escalating — the caller writes it back onto the entry.
    """

    kind: str
    retries: int
    cooldown_until: str | None = None


def apply_retry_gate(
    entry: Mapping[str, Any],
    now: str,
    *,
    max_retries: int,
    escalate_cooldown_hours: float,
) -> Decision:
    """Decide skip / act / escalate for one retry-tracker entry.

    Mirrors ``sweeps.py:116-118`` exactly: cooldown is an ISO-string ``<``
    compare (matching the shell ``\\<``); the cap is ``>=``; escalation sets a
    fresh cooldown ``escalate_cooldown_hours`` ahead of ``now``.
    """
    retries = int(entry.get("retries") or 0)
    cooldown = str(entry.get("cooldown_until") or "")
    if cooldown and now < cooldown:
        return Decision(kind="skip", retries=retries)
    if retries >= max_retries:
        return Decision(
            kind="escalate",
            retries=retries,
            cooldown_until=shift(now, hours=escalate_cooldown_hours),
        )
    return Decision(kind="act", retries=retries)
