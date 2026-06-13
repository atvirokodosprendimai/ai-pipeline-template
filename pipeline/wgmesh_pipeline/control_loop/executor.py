"""Control-loop action executor — the single write path behind the sanitise wall.

The four planners (supervisor / selfheal / observation / strategy_audit) emit
planned actions; this module is the ONLY place those plans become forge writes.
``execute_action`` is a pure dispatch table: it maps each of the 12 action kinds
to the right ``Forge`` write method and returns an ``ExecutionResult``.

Safety posture (cardinal rules, all enforced here):

  - **Sanitise wall** — every comment/issue/PR body emit is gated by
    ``company/scripts/sanitise.sh`` *before* the write. The forge write methods
    already run the gate inside ``_write`` (the lowest boundary), so routing
    through them is the gate. A ``SanitiseError`` BLOCKS that one action
    (status="blocked") and is logged; it NEVER aborts the cycle or the batch
    (LLM-emit lesson).
  - **Fail-closed, batch-resilient** — any exception from one action becomes an
    ``error`` result and is logged; the batch continues (one bad action must not
    kill convergence).
  - **Unknown kind = loud skip** — an unrecognised kind logs a warning and
    returns ``status="skipped"`` (never a silent drop; defensive-guard-must-
    announce lesson).
  - **Idempotent-tolerant** — already-closed / already-merged hosts errors are
    expected and surface as ``error`` results, not crashes; the caller treats a
    repeat as a no-op.

Mode-neutral by construction: the executor does not branch on shadow vs live.
In shadow the injected forge returns ``DryRunResult`` records and performs zero
HTTP — the executor routes identically, proving the path without writing. The
scheduler only *calls* the executor when ``control_loop_mode == "live"``; in
shadow it logs (current behaviour). State persistence is U3, not here — ``store``
is threaded through for that seam and idempotency lookups.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from wgmesh_pipeline.forge.protocol import Forge
from wgmesh_pipeline.github.client import SanitiseError

log = logging.getLogger("wgmesh_pipeline.control_loop.executor")

NEEDS_HUMAN_LABEL = "needs-human"
OBSERVATION_WORKFLOW = "observation-loop.yml"
DEFAULT_CLOSE_STATE_REASON = "not planned"

# Status vocabulary for an ExecutionResult.
EXECUTED = "executed"  # the forge write (or dry-run) ran
BLOCKED = "blocked"  # sanitise gate refused this action (fail-closed)
SKIPPED = "skipped"  # unknown kind, or a malformed action — loud, never silent
ERROR = "error"  # the forge raised (incl. idempotent already-closed hosts errors)


class PlannedAction(Protocol):
    """Structural view of both ``HealAction`` and ``ObservationAction`` — the
    only fields the dispatch table reads. Frozen dataclasses both satisfy it."""

    kind: str


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of one ``execute_action`` call. ``raw`` is the forge return
    (a ``DryRunResult`` in shadow, the HTTP body in live, or None)."""

    kind: str
    status: str
    detail: str = ""
    raw: Any = None


def _attr(action: Any, name: str, default: Any = None) -> Any:
    """Read an optional field present on one action dataclass but not the other
    (HealAction vs ObservationAction have overlapping-but-distinct fields)."""
    return getattr(action, name, default)


# --- per-kind handlers ------------------------------------------------------
#
# Each handler performs the forge write(s) for one kind and returns the forge's
# raw result. They never catch exceptions — execute_action() owns the
# fail-closed / batch-resilient wrapper so the posture is uniform.


def _h_create_issue(forge: Forge, action: Any) -> Any:
    """create_issue / create_needs_human — open a new issue with its labels."""
    title = str(_attr(action, "title") or "")
    body = str(_attr(action, "body") or "")
    labels = tuple(_attr(action, "labels") or ())
    return forge.create_issue(title=title, body=body, labels=labels)


def _h_create_needs_human_issue(forge: Forge, action: Any) -> Any:
    """escalate / supervisor_dead / circuit_breaker on a *repo* target — these
    plan a NEW needs-human issue (no existing number), title+body carried."""
    title = str(_attr(action, "title") or "")
    body = str(_attr(action, "body") or "")
    return forge.create_issue(title=title, body=body, labels=(NEEDS_HUMAN_LABEL,))


def _h_escalate(forge: Forge, action: Any) -> Any:
    """escalate — comment the rationale on an EXISTING issue then add
    needs-human. When no number is present it is a repo-level escalation
    (create the issue instead — supervisor_dead/circuit_breaker shape)."""
    number = _attr(action, "number")
    if number is None:
        return _h_create_needs_human_issue(forge, action)
    body = str(_attr(action, "body") or _attr(action, "comment") or "")
    if body:
        forge.comment(int(number), body)
    return forge.add_label(int(number), NEEDS_HUMAN_LABEL)


def _h_close_issue(forge: Forge, action: Any) -> Any:
    """close_issue (observation) — the comment text and the close reason are
    carried separately; close_issue posts the human-facing comment + flips
    state. Default state_reason 'not planned' (COMPLETED is the merged-impl
    closer's, R5)."""
    number = int(_attr(action, "number"))
    comment = str(_attr(action, "comment") or _attr(action, "reason") or "")
    state_reason = str(_attr(action, "close_reason") or DEFAULT_CLOSE_STATE_REASON)
    return forge.close_issue(number, comment, state_reason=state_reason)


def _h_close_needs_human(forge: Forge, action: Any) -> Any:
    """close_needs_human (selfheal) — a fulfilled needs-human issue. Carries a
    resolution comment, no explicit close reason → default 'not planned'."""
    number = int(_attr(action, "number"))
    comment = str(_attr(action, "comment") or _attr(action, "reason") or "")
    return forge.close_issue(number, comment)


def _h_close_pr(forge: Forge, action: Any) -> Any:
    number = int(_attr(action, "number"))
    comment = str(_attr(action, "comment") or _attr(action, "reason") or "")
    return forge.close_pr(number, comment)


def _h_retrigger(forge: Forge, action: Any) -> Any:
    """retrigger_triage / retrigger_copilot / retrigger_goose — the workflow's
    label toggle (remove the stage label, re-add the target label) that
    restarts a stalled lane. Both writes go through the gate (label names)."""
    number = int(_attr(action, "number"))
    remove_label = _attr(action, "remove_label")
    add_label = _attr(action, "add_label")
    if remove_label:
        forge.remove_label(number, str(remove_label))
    if add_label:
        return forge.add_label(number, str(add_label))
    return None


def _h_dispatch_observation_loop(forge: Forge, action: Any) -> Any:
    """dispatch_observation_loop — fire the observation-loop workflow. The
    HealAction body carries the idle signal context; pass it as a dispatch
    input. On a host without workflow_dispatch this no-ops (Gitea seam)."""
    body = str(_attr(action, "body") or "")
    reason = str(_attr(action, "reason") or "")
    return forge.dispatch_workflow(
        OBSERVATION_WORKFLOW, {"signal": body, "reason": reason}
    )


# kind -> handler. The 12 planner kinds, exhaustively.
_DISPATCH = {
    "create_issue": _h_create_issue,
    "create_needs_human": _h_create_issue,
    "escalate": _h_escalate,
    "supervisor_dead": _h_create_needs_human_issue,
    "circuit_breaker": _h_create_needs_human_issue,
    "close_issue": _h_close_issue,
    "close_needs_human": _h_close_needs_human,
    "close_pr": _h_close_pr,
    "retrigger_triage": _h_retrigger,
    "retrigger_copilot": _h_retrigger,
    "retrigger_goose": _h_retrigger,
    "dispatch_observation_loop": _h_dispatch_observation_loop,
}


def execute_action(forge: Forge, store: Any, action: Any) -> ExecutionResult:
    """Execute one planned action through the forge, behind the sanitise wall.

    Pure dispatch with a uniform safety wrapper:
      - unknown kind -> loud ``skipped`` (never silent);
      - ``SanitiseError`` -> ``blocked`` + log (fail-closed, batch continues);
      - any other exception -> ``error`` + log (idempotent host errors land
        here too; the batch is never aborted).

    ``store`` is accepted for the U3 persistence/idempotency seam; this unit
    does not read or write it.
    """
    kind = str(_attr(action, "kind") or "")
    handler = _DISPATCH.get(kind)
    if handler is None:
        log.warning(
            "control_loop.executor: unknown action kind %r — skipping (loud, "
            "never silent). action=%r",
            kind,
            action,
        )
        return ExecutionResult(kind=kind, status=SKIPPED, detail="unknown kind")

    try:
        raw = handler(forge, action)
    except SanitiseError as exc:
        # The sanitise wall refused this emit. Block THIS action only — never
        # abort the batch (LLM-emit lesson). Logged loudly.
        log.warning(
            "control_loop.executor: sanitise gate BLOCKED %s action: %s — "
            "skipping this action (batch continues)",
            kind,
            exc,
        )
        return ExecutionResult(kind=kind, status=BLOCKED, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — loud log, never swallow; never abort batch
        log.exception(
            "control_loop.executor: %s action failed: %s — recording error "
            "(batch continues; idempotent host errors are expected here)",
            kind,
            exc,
        )
        return ExecutionResult(kind=kind, status=ERROR, detail=str(exc))

    return ExecutionResult(kind=kind, status=EXECUTED, raw=raw)


def execute_actions(forge: Forge, store: Any, actions: Any) -> list[ExecutionResult]:
    """Execute a batch. One action raising never aborts the rest — each is
    wrapped independently by ``execute_action``."""
    return [execute_action(forge, store, action) for action in actions]
