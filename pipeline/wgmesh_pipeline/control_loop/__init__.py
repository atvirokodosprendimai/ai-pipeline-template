"""Box-side Control-Loop scheduler — SHADOW-ONLY (cutover Phase B/C bake).

The four control-loop planners (``supervisor.run_supervisor_rank``,
``selfheal.run_self_heal``, ``observation.plan_actions``,
``strategy_audit.run_strategy_audit``) are parity-passive: they gather/return
state + planned actions but never write. This scheduler wires them into the box
loop on per-module cadences and, for each cycle, does exactly three things:
gather inputs, call the planner, and LOG a structured one-line summary. It
performs ZERO forge writes and ZERO state persistence — the zero-blast-radius
bake before a later live flip.

The LIVE executor is a separate follow-up unit. It will, behind the
``company/scripts/sanitise.sh`` wall, publish the planned actions and persist
the returned state dicts (to Turso / the ``company/*.json`` state files), gated
on each planner's ``material_changed`` sentinel. None of that lives here.

``control_loop_mode == "live"`` is honored as SHADOW in this unit (forced back
with a loud warning) because that executor does not exist yet — going live
without it would write blind.

Per-module gather gaps (honest degradation — these are the follow-up unit's
TODOs, NOT to be faked here):
  - supervisor: ``previous_state`` is not loaded in shadow (passed None), so
    rank-change/run-counter deltas reset each cycle; the forge snapshot is the
    degraded ``snapshot_from_forge`` (no timestamps → dwell 0, single repo).
  - selfheal: only the forge-derivable ``needs_human_issues`` is populated; the
    label-filtered stale sweeps + funnel/idle snapshot dicts stay at their
    empty defaults (the protocol cannot feed them yet).
  - observation: the LLM assessment dict is caller-side and NOT built here — the
    cycle logs a skip and does nothing (never fabricate an assessment).
  - strategy_audit: STRATEGY.md is read if present, but live metrics (GitHub /
    chimney / Polar reads) are not gatherable yet — the cycle logs a skip.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.control_loop.executor import execute_actions
from wgmesh_pipeline.forge.protocol import Forge
from wgmesh_pipeline.selfheal import SelfHealInputs, SelfHealRun, run_self_heal
from wgmesh_pipeline.supervisor import (
    SupervisorRankRun,
    load_taxonomy,
    run_supervisor_rank,
)

log = logging.getLogger("wgmesh_pipeline.control_loop")

# Repo root holds company/ (taxonomy) and STRATEGY.md. This module lives at
# <root>/pipeline/wgmesh_pipeline/control_loop/__init__.py, so parents[3] is
# the repo root (control_loop/ -> wgmesh_pipeline/ -> pipeline/ -> root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TAXONOMY_PATH = _REPO_ROOT / "company" / "pipeline-stages.json"
_STRATEGY_PATH = _REPO_ROOT / "STRATEGY.md"

SHADOW = "shadow"

# control_loop_state row keys — one per persisted module. These mirror the
# committed company/*.json snapshots, which become read-only once a module is
# live (the box store is the authoritative copy).
SUPERVISOR_STATE_KEY = "supervisor-rank-state"
SELFHEAL_STATE_KEY = "pipeline-health-state"
STRATEGY_AUDIT_STATE_KEY = "strategy-audit-baseline"

# pipeline-health state keys that change every run regardless of material
# activity (timestamps/counters). Excluded from the selfheal material
# fingerprint so an idle cycle does not churn a new persisted copy
# (gate-state-commit-on-material-change lesson).
_SELFHEAL_VOLATILE_KEYS = frozenset(
    {"last_check", "checks_run", "last_mutation_asserted_at", "last_run_summary"}
)


def _material_fingerprint(doc: Mapping[str, Any], *, exclude: frozenset[str]) -> str:
    """Stable sha256 over a state dict with volatile keys removed — the
    anti-churn fingerprint for modules that don't expose their own."""
    material = {k: v for k, v in doc.items() if k not in exclude}
    payload = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# Injectable planner callable types (real ones default in ``ControlLoopScheduler``
# so tests inject spies without touching the forge/LLM).
SupervisorPlanner = Callable[..., SupervisorRankRun]
SelfHealPlanner = Callable[[Forge, SelfHealInputs], SelfHealRun]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _load_taxonomy_or_empty() -> Mapping[str, Any]:
    """Taxonomy for supervisor-rank; degrade to ``{}`` (documented gap) when the
    file is absent so a missing config never crashes the scheduler."""
    try:
        return load_taxonomy(_TAXONOMY_PATH)
    except (OSError, ValueError) as exc:
        log.warning(
            "control_loop: taxonomy unavailable (%s) — supervisor runs degraded "
            "with an empty taxonomy",
            exc,
        )
        return {}


@dataclass(frozen=True)
class ModuleTask:
    """One scheduled control-loop slot: a name, its cadence, and the cycle
    coroutine factory. ``interval_seconds`` is read off the config per module."""

    name: str
    interval_seconds: int
    run_cycle: Callable[[], Any]  # async callable: one gather→plan→log cycle


@dataclass
class ControlLoopScheduler:
    """Runs each enabled control-loop planner on its own cadence, shadow-only.

    Every cycle is wrapped in try/except: one module raising is logged
    (``log.exception``) and the task continues to its next interval — a single
    crashing planner never kills the loop or its siblings (poller posture: loud
    log, never silent swallow). Stop is interruptible mid-interval, mirroring
    ``Poller.run_forever``'s ``asyncio.wait_for(stop.wait(), timeout=...)``.
    """

    config: Config
    forge: Forge
    store: object  # StateStore — never written in shadow; held for the live unit
    log: logging.Logger = log
    supervisor_planner: SupervisorPlanner = run_supervisor_rank
    selfheal_planner: SelfHealPlanner = run_self_heal
    _tasks: list[ModuleTask] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.config.control_loop_mode != SHADOW:
            self.log.warning(
                "control_loop: CONTROL_LOOP_MODE=%r is not honored in this unit — "
                "the live executor (forge writes + state persistence) is a "
                "follow-up; FORCING shadow (zero writes).",
                self.config.control_loop_mode,
            )
        self._tasks = [
            ModuleTask("selfheal", self.config.selfheal_interval_seconds, self._cycle_selfheal),
            ModuleTask("supervisor", self.config.supervisor_interval_seconds, self._cycle_supervisor),
            ModuleTask("observation", self.config.observation_interval_seconds, self._cycle_observation),
            ModuleTask(
                "strategy_audit",
                self.config.strategy_audit_interval_seconds,
                self._cycle_strategy_audit,
            ),
        ]

    @property
    def tasks(self) -> tuple[ModuleTask, ...]:
        return tuple(self._tasks)

    async def run(self, stop: asyncio.Event | None = None) -> None:
        """Start every module task and run until ``stop`` is set, then cancel
        them cleanly. Shadow-only: no writes, no persistence."""
        stop = stop or asyncio.Event()
        self.log.info(
            "control_loop: starting shadow scheduler tasks=%s "
            "(selfheal=%ss supervisor=%ss observation=%ss strategy_audit=%ss)",
            [t.name for t in self._tasks],
            self.config.selfheal_interval_seconds,
            self.config.supervisor_interval_seconds,
            self.config.observation_interval_seconds,
            self.config.strategy_audit_interval_seconds,
        )
        coros = [self._run_task(task, stop) for task in self._tasks]
        runners = [asyncio.ensure_future(c) for c in coros]
        try:
            await asyncio.gather(*runners)
        finally:
            for runner in runners:
                runner.cancel()
            await asyncio.gather(*runners, return_exceptions=True)

    async def _run_task(self, task: ModuleTask, stop: asyncio.Event) -> None:
        """Periodic loop for one module: run a cycle, then wait the interval
        (interruptible by ``stop``). A cycle exception is logged and the loop
        continues — siblings and the scheduler are unaffected."""
        while not stop.is_set():
            try:
                await task.run_cycle()
            except Exception as exc:  # noqa: BLE001 — loud log, never swallow
                self.log.exception(
                    "control_loop: %s cycle failed: %s — continuing to next interval",
                    task.name,
                    exc,
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=task.interval_seconds)
            except (TimeoutError, asyncio.TimeoutError):
                continue

    # --- state persistence (box-internal; happens in shadow + live) -------

    def _load_state(self, key: str) -> Mapping[str, Any] | None:
        """Load a module's previous persisted state, or None. Tolerates a store
        without the control-state API (returns None) so a misconfigured store
        degrades to the prior 'no previous_state' behaviour, loudly logged once
        per failure rather than crashing the cycle."""
        loader = getattr(self.store, "load_control_state", None)
        if loader is None:
            return None
        try:
            return loader(key)
        except Exception as exc:  # noqa: BLE001 — never let a store read kill the cycle
            self.log.warning("control_loop: load_control_state(%s) failed: %s", key, exc)
            return None

    def _save_state(self, key: str, doc: Mapping[str, Any], fingerprint: str) -> bool:
        """Persist a module's state, deduped on the fingerprint. Box-internal
        state — not a forge write — so it runs in shadow and live alike. A store
        without the API or a failed write is logged, never fatal."""
        saver = getattr(self.store, "save_control_state", None)
        if saver is None:
            return False
        try:
            return bool(saver(key, dict(doc), fingerprint=fingerprint))
        except Exception as exc:  # noqa: BLE001 — never let a store write kill the cycle
            self.log.warning("control_loop: save_control_state(%s) failed: %s", key, exc)
            return False

    # --- per-module cycles: gather → plan → log structured summary --------

    async def _cycle_supervisor(self) -> None:
        taxonomy = _load_taxonomy_or_empty()
        # U3: load the previous persisted copy so rank-change/run-counter deltas
        # survive across cycles (closes the "previous_state not loaded" gap).
        previous_state = self._load_state(SUPERVISOR_STATE_KEY)
        run = self.supervisor_planner(
            self.forge,
            taxonomy=taxonomy,
            repo=self.config.repo,  # short name ("wgmesh") — supervisor IDs are "repo#N" (parity)
            previous_state=previous_state,
            now=None,
        )
        # Persist only on material change (anti PR-per-run pile-up). The
        # supervisor exposes its own material_fingerprint in the state dict.
        persisted = False
        if run.material_changed:
            fingerprint = str(run.state.get("material_fingerprint") or "")
            persisted = self._save_state(SUPERVISOR_STATE_KEY, run.state, fingerprint)
        top_actions = [str(a.get("action")) for a in run.result.top_actions if a.get("action")]
        self.log.info(
            "control_loop: module=supervisor mode=%s material_changed=%s "
            "rank_changed=%s planned_actions=%s top_actions=%s "
            "previous_state_loaded=%s persisted=%s (forge snapshot degraded)",
            self.config.control_loop_mode,
            run.material_changed,
            run.rank_changed,
            len(run.result.top),
            top_actions[:3],
            previous_state is not None,
            persisted,
        )

    async def _cycle_selfheal(self) -> None:
        inputs = SelfHealInputs(now=_utc_now_iso())  # forge-derivable only; rest degraded
        run = self.selfheal_planner(self.forge, inputs)
        action_kinds = [a.kind for a in run.actions]
        # Route every planned action through the single executor. The executor
        # is mode-neutral: in shadow the forge dry-runs (DryRunResult, zero
        # HTTP), in live it writes — behind the sanitise wall either way. One
        # action raising never aborts the batch (fail-closed, per-action).
        results = execute_actions(self.forge, self.store, run.actions)
        statuses = [r.status for r in results]
        # U3: persist the heal state on material activity only. Selfheal exposes
        # no fingerprint of its own, so material = some action planned or the
        # breaker tripped; an idle no-op cycle never churns a persisted copy.
        # The store also dedupes on a fingerprint over the non-volatile fields.
        persisted = False
        material = bool(run.actions) or run.circuit_breaker_tripped
        if material:
            fingerprint = _material_fingerprint(run.state, exclude=_SELFHEAL_VOLATILE_KEYS)
            persisted = self._save_state(SELFHEAL_STATE_KEY, run.state, fingerprint)
        self.log.info(
            "control_loop: module=selfheal mode=%s circuit_breaker_tripped=%s "
            "mutation_asserted=%s planned_actions=%s top_actions=%s "
            "executed=%s result_statuses=%s persisted=%s "
            "(gap: stale-sweep + funnel/idle snapshots empty)",
            self.config.control_loop_mode,
            run.circuit_breaker_tripped,
            run.mutation_asserted,
            len(run.actions),
            action_kinds[:3],
            sum(1 for s in statuses if s == "executed"),
            statuses[:5],
            persisted,
        )

    async def _cycle_observation(self) -> None:
        # The LLM assessment dict is caller-side and not yet wired. Do NOT
        # fabricate an assessment — log the gap and end the cycle (still a
        # scheduled slot).
        self.log.info(
            "control_loop: module=observation mode=shadow "
            "skipped: LLM assessment input not yet wired (protocol/gather gap) — "
            "planned_actions=0"
        )

    async def _cycle_strategy_audit(self) -> None:
        strategy_text = _read_text(_STRATEGY_PATH)
        # Live metrics (GitHub / chimney / Polar reads) are caller-side and not yet
        # gatherable. Without them the audit cannot run honestly — log the gap
        # and end the cycle (still a scheduled slot).
        self.log.info(
            "control_loop: module=strategy_audit mode=shadow "
            "skipped: live metrics gather not yet wired — strategy_text=%s "
            "planned_actions=0",
            "present" if strategy_text is not None else "absent",
        )
