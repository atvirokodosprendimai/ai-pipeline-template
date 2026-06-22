"""Box-side Control-Loop scheduler with per-module live gates.

The four control-loop planners (``supervisor.run_supervisor_rank``,
``selfheal.run_self_heal``, ``observation.plan_actions``,
``strategy_audit.run_strategy_audit``) gather/return state + planned actions.
Each module is shadow by default and only executes/persists when its own
``*_LIVE`` config flag is true. ``PIPELINE_MODE`` and ``CONTROL_LOOP_MODE`` are
not the control-loop write gate.

Per-module gather gaps (honest degradation — these are the follow-up unit's
TODOs, NOT to be faked here):
  - supervisor: ``previous_state`` is not loaded in shadow (passed None), so
    rank-change/run-counter deltas reset each cycle; the forge snapshot is the
    degraded ``snapshot_from_forge`` (no timestamps → dwell 0, single repo).
  - selfheal: only the forge-derivable ``needs_human_issues`` is populated; the
    label-filtered stale sweeps + funnel/idle snapshot dicts stay at their
    empty defaults (the protocol cannot feed them yet).
  - observation: closed issue titles still degrade to ``()`` until the forge
    protocol grows a closed-title read.
  - strategy_audit: lead-time/autonomous-ship metrics degrade to ``None`` unless
    the concrete forge exposes optional recent-merged-PR/timeline reads.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.control_loop.executor import ExecutionResult, execute_actions
from wgmesh_pipeline.forge.protocol import Forge
from wgmesh_pipeline.observation import ObservationPlan, plan_actions
from wgmesh_pipeline.selfheal import (
    MergeLaneHealRun,
    SelfHealInputs,
    SelfHealRun,
    run_merge_lane_heal,
    run_self_heal,
)

# The gather modules import wgmesh_pipeline.control_loop.executor, so importing
# them at module top creates a circular import (this package's __init__ would
# re-enter mid-load). Runtime symbols are imported lazily inside the cycle
# methods; type-only names live in the TYPE_CHECKING block below.
if TYPE_CHECKING:
    from wgmesh_pipeline.observation_gather import (
        ObservationAssessor,
        ObservationCycleResult,
        ObservationPlanner,
    )
    from wgmesh_pipeline.strategy_gather import HttpGet, StrategyCycleResult
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
LIVE = "live"
SHADOW_REASON = "module not flipped live"

# control_loop_state row keys — one per persisted module. These mirror the
# committed company/*.json snapshots, which become read-only once a module is
# live (the box store is the authoritative copy).
SUPERVISOR_STATE_KEY = "supervisor-rank-state"
SELFHEAL_STATE_KEY = "pipeline-health-state"
STRATEGY_AUDIT_STATE_KEY = "strategy-audit-baseline"
# Merge-lane-heal persists a separate retry-tracker per repo (the module heals
# BOTH the seed and the meta repo each cycle), mirroring the retired cron's
# per-repo state files.
MERGE_LANE_STATE_KEY_BY_LABEL = {
    "seed": "merge-lane-heal-state-seed",
    "meta": "merge-lane-heal-state-meta",
}

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
StrategyTextReader = Callable[[], str | None]
NowProvider = Callable[[], str]
ActionExecutor = Callable[[Forge, object, Sequence[Any]], list[ExecutionResult]]
MergeLanePlanner = Callable[..., MergeLaneHealRun]
# (config, repo_slug) -> a GitHub client for that repo. Injectable so tests
# drive merge-lane-heal with a fake forge instead of real HTTP.
MergeLaneClientFactory = Callable[[Config, str], Any]


def _default_merge_lane_client(config: Config, repo_slug: str) -> Any:
    """Build a GitHub client bound to ``repo_slug``. Merge-lane-heal always
    targets GitHub (PRs live there even when the seed forge is Quackback), so
    this constructs a GitHubClient directly rather than reusing ``self.forge``.
    Imported lazily to avoid a control_loop ↔ github.client import cycle."""
    from wgmesh_pipeline.github.client import GitHubClient

    return GitHubClient(replace(config, target_repo=repo_slug))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _shadow_executor(
    forge: Forge, store: object, actions: Sequence[Any]
) -> list[ExecutionResult]:
    return []


@dataclass(frozen=True)
class _ShadowStore:
    """Read-only store view for shadow cycles that need prior state as input."""

    store: object

    def load_control_state(self, key: str) -> Mapping[str, Any] | None:
        loader = getattr(self.store, "load_control_state", None)
        if loader is None:
            return None
        loaded = loader(key)
        return loaded if isinstance(loaded, Mapping) else None


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
    """Runs each enabled control-loop planner on its own cadence.

    Every cycle is wrapped in try/except: one module raising is logged
    (``log.exception``) and the task continues to its next interval — a single
    crashing planner never kills the loop or its siblings (poller posture: loud
    log, never silent swallow). Stop is interruptible mid-interval, mirroring
    ``Poller.run_forever``'s ``asyncio.wait_for(stop.wait(), timeout=...)``.
    """

    config: Config
    forge: Forge
    store: object
    log: logging.Logger = log
    supervisor_planner: SupervisorPlanner = run_supervisor_rank
    selfheal_planner: SelfHealPlanner = run_self_heal
    observation_assessor: ObservationAssessor | None = None
    observation_planner: ObservationPlanner = plan_actions
    strategy_text_reader: StrategyTextReader = lambda: _read_text(_STRATEGY_PATH)
    strategy_http_get: HttpGet | None = None
    now_provider: NowProvider = _utc_now_iso
    action_executor: ActionExecutor = execute_actions
    merge_lane_planner: MergeLanePlanner = run_merge_lane_heal
    merge_lane_client_factory: MergeLaneClientFactory = _default_merge_lane_client
    _tasks: list[ModuleTask] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._tasks = [
            ModuleTask(
                "selfheal", self.config.selfheal_interval_seconds, self._cycle_selfheal
            ),
            ModuleTask(
                "supervisor",
                self.config.supervisor_interval_seconds,
                self._cycle_supervisor,
            ),
            ModuleTask(
                "observation",
                self.config.observation_interval_seconds,
                self._cycle_observation,
            ),
            ModuleTask(
                "strategy_audit",
                self.config.strategy_audit_interval_seconds,
                self._cycle_strategy_audit,
            ),
            ModuleTask(
                "merge_lane",
                self.config.merge_lane_heal_interval_seconds,
                self._cycle_merge_lane,
            ),
            ModuleTask(
                "decision",
                self.config.decision_lane_interval_seconds,
                self._cycle_decision,
            ),
        ]
        for task in self._tasks:
            self.log.info(
                "control_loop: module=%s startup_mode=%s",
                task.name,
                LIVE if self._module_live(task.name) else SHADOW,
            )

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

    def _module_live(self, module_name: str) -> bool:
        live_by_module = {
            "supervisor": self.config.supervisor_live,
            "selfheal": self.config.selfheal_live,
            "observation": self.config.observation_live,
            "strategy_audit": self.config.strategy_audit_live,
            "merge_lane": self.config.merge_lane_heal_live,
            "decision": self.config.decision_lane_live,
        }
        try:
            return live_by_module[module_name]
        except KeyError as exc:
            raise ValueError(f"unknown control-loop module {module_name!r}") from exc

    def _module_mode(self, module_name: str) -> str:
        return LIVE if self._module_live(module_name) else SHADOW

    def _shadow_store(self, module_name: str) -> object:
        return (
            self.store if self._module_live(module_name) else _ShadowStore(self.store)
        )

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
            self.log.warning(
                "control_loop: load_control_state(%s) failed: %s", key, exc
            )
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
        except (
            Exception
        ) as exc:  # noqa: BLE001 — never let a store write kill the cycle
            self.log.warning(
                "control_loop: save_control_state(%s) failed: %s", key, exc
            )
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
        top_actions = [
            str(a.get("action")) for a in run.result.top_actions if a.get("action")
        ]
        if not self._module_live("supervisor"):
            self.log.info(
                "control_loop: module=supervisor mode=shadow material_changed=%s "
                "rank_changed=%s planned_actions=%s executed=0 "
                'reason="module not flipped live" top_actions=%s '
                "previous_state_loaded=%s persisted=false (forge snapshot degraded)",
                run.material_changed,
                run.rank_changed,
                len(top_actions),
                top_actions[:3],
                previous_state is not None,
            )
            return
        # Persist only on material change (anti PR-per-run pile-up). The
        # supervisor exposes its own material_fingerprint in the state dict.
        persisted = False
        if run.material_changed:
            fingerprint = str(run.state.get("material_fingerprint") or "")
            persisted = self._save_state(SUPERVISOR_STATE_KEY, run.state, fingerprint)
        self.log.info(
            "control_loop: module=supervisor mode=%s material_changed=%s "
            "rank_changed=%s planned_actions=%s executed=0 top_actions=%s "
            "previous_state_loaded=%s persisted=%s (forge snapshot degraded)",
            self._module_mode("supervisor"),
            run.material_changed,
            run.rank_changed,
            len(top_actions),
            top_actions[:3],
            previous_state is not None,
            persisted,
        )

    async def _cycle_selfheal(self) -> None:
        inputs = SelfHealInputs(
            now=_utc_now_iso()
        )  # forge-derivable only; rest degraded
        run = self.selfheal_planner(self.forge, inputs)
        action_kinds = [a.kind for a in run.actions]
        if not self._module_live("selfheal"):
            self.log.info(
                "control_loop: module=selfheal mode=shadow "
                "circuit_breaker_tripped=%s mutation_asserted=%s "
                "planned_actions=%s top_actions=%s executed=0 "
                'reason="module not flipped live" persisted=false '
                "(gap: stale-sweep + funnel/idle snapshots empty)",
                run.circuit_breaker_tripped,
                run.mutation_asserted,
                len(run.actions),
                action_kinds[:3],
            )
            return
        # Route every planned action through the single executor. The executor
        # is mode-neutral: in shadow the forge dry-runs (DryRunResult, zero
        # HTTP), in live it writes — behind the sanitise wall either way. One
        # action raising never aborts the batch (fail-closed, per-action).
        results = self.action_executor(self.forge, self.store, run.actions)
        statuses = [r.status for r in results]
        # U3: persist the heal state on material activity only. Selfheal exposes
        # no fingerprint of its own, so material = some action planned or the
        # breaker tripped; an idle no-op cycle never churns a persisted copy.
        # The store also dedupes on a fingerprint over the non-volatile fields.
        persisted = False
        material = bool(run.actions) or run.circuit_breaker_tripped
        if material:
            fingerprint = _material_fingerprint(
                run.state, exclude=_SELFHEAL_VOLATILE_KEYS
            )
            persisted = self._save_state(SELFHEAL_STATE_KEY, run.state, fingerprint)
        self.log.info(
            "control_loop: module=selfheal mode=%s circuit_breaker_tripped=%s "
            "mutation_asserted=%s planned_actions=%s top_actions=%s "
            "executed=%s result_statuses=%s persisted=%s "
            "(gap: stale-sweep + funnel/idle snapshots empty)",
            self._module_mode("selfheal"),
            run.circuit_breaker_tripped,
            run.mutation_asserted,
            len(run.actions),
            action_kinds[:3],
            sum(1 for s in statuses if s == "executed"),
            statuses[:5],
            persisted,
        )

    async def _cycle_observation(self) -> None:
        from wgmesh_pipeline.observation_gather import (
            GooseObservationAssessor,
            run_observation_cycle,
        )

        assessor = self.observation_assessor or GooseObservationAssessor(
            self.config, _REPO_ROOT
        )
        result: ObservationCycleResult = run_observation_cycle(
            self.forge,
            self.store,
            assessor=assessor,
            planner=self.observation_planner,
            executor=(
                self.action_executor
                if self._module_live("observation")
                else _shadow_executor
            ),
        )
        if result.skipped:
            self.log.warning(
                "control_loop: module=observation mode=%s skipped=%s "
                "reason=%s planned_actions=0 executed=0",
                self._module_mode("observation"),
                result.skipped,
                result.skip_reason,
            )
            return
        statuses = [r.status for r in result.execution_results]
        planned = (
            len(result.plan.actions) if isinstance(result.plan, ObservationPlan) else 0
        )
        if not self._module_live("observation"):
            self.log.info(
                "control_loop: module=observation mode=shadow "
                "planned_actions=%s skips=%s executed=0 "
                'reason="module not flipped live" result_statuses=%s',
                planned,
                len(result.plan.skips) if result.plan is not None else 0,
                statuses[:5],
            )
            return
        self.log.info(
            "control_loop: module=observation mode=%s planned_actions=%s "
            "skips=%s executed=%s result_statuses=%s",
            self._module_mode("observation"),
            planned,
            len(result.plan.skips) if result.plan is not None else 0,
            sum(1 for status in statuses if status == "executed"),
            statuses[:5],
        )

    async def _cycle_strategy_audit(self) -> None:
        from wgmesh_pipeline.strategy_gather import run_strategy_cycle

        strategy_text = self.strategy_text_reader()
        if strategy_text is None:
            self.log.warning(
                "control_loop: module=strategy_audit mode=%s skipped=true "
                "reason=STRATEGY.md unavailable planned_actions=0 executed=0",
                self._module_mode("strategy_audit"),
            )
            return
        kwargs: dict[str, Any] = {
            "strategy_text": strategy_text,
            "now": self.now_provider(),
        }
        if self.strategy_http_get is not None:
            kwargs["http_get"] = self.strategy_http_get
        result: StrategyCycleResult = run_strategy_cycle(
            self.forge,
            self._shadow_store("strategy_audit"),
            executor=(
                self.action_executor
                if self._module_live("strategy_audit")
                else _shadow_executor
            ),
            **kwargs,
        )
        planned = 1 if result.run.decision.action == "open_pr" else 0
        statuses = [r.status for r in result.execution_results]
        if not self._module_live("strategy_audit"):
            self.log.info(
                "control_loop: module=strategy_audit mode=shadow decision=%s "
                "material_changed=%s planned_actions=%s executed=0 "
                'reason="module not flipped live" result_statuses=%s '
                "persisted=false paid_fetch_status=%s",
                result.run.decision.action,
                result.run.material_changed,
                planned,
                statuses[:5],
                result.metrics.paid_fetch_status,
            )
            return
        self.log.info(
            "control_loop: module=strategy_audit mode=%s decision=%s "
            "material_changed=%s planned_actions=%s executed=%s "
            "result_statuses=%s persisted=%s paid_fetch_status=%s",
            self._module_mode("strategy_audit"),
            result.run.decision.action,
            result.run.material_changed,
            planned,
            sum(1 for status in statuses if status == "executed"),
            statuses[:5],
            result.persisted,
            result.metrics.paid_fetch_status,
        )

    async def _cycle_merge_lane(self) -> None:
        """Merge-lane-heal across BOTH repos (seed + meta). PRs always live on
        GitHub even when the seed forge is Quackback, so this builds a dedicated
        GitHub client per repo (not ``self.forge``). Shadow plans + logs but
        executes nothing; live rebases/re-arms via the forge + ``rebase.sh`` and
        persists the per-repo retry tracker on material activity. One repo
        raising is caught by ``_run_task`` and never blocks the other."""
        live = self._module_live("merge_lane")
        # No bot token → no PR reads/writes possible on either repo. Skip the
        # whole cycle (also keeps tests, which carry no PAT, off the network).
        if not self.config.wgmesh_bot_pat:
            self.log.info(
                "control_loop: module=merge_lane mode=%s skipped=true "
                "reason=no-bot-token planned_actions=0 executed=0",
                LIVE if live else SHADOW,
            )
            return
        now = self.now_provider()
        for label, repo_slug in (
            ("seed", self.config.target_repo),
            ("meta", self.config.meta_repo),
        ):
            # Per-repo isolation: one repo's HTTP/rebase failure is logged and
            # never blocks the other (and never the scheduler — _run_task wraps).
            try:
                client = self.merge_lane_client_factory(self.config, repo_slug)
                state_key = MERGE_LANE_STATE_KEY_BY_LABEL[label]
                prev_state = self._load_state(state_key) or {}
                run: MergeLaneHealRun = self.merge_lane_planner(
                    client, prev_state, now, live=live, repo_label=label
                )
            except Exception as exc:  # noqa: BLE001 — loud log, isolate the repo
                self.log.exception(
                    "control_loop: module=merge_lane repo=%s cycle failed: %s",
                    label,
                    exc,
                )
                continue
            action_kinds = [a.kind for a in run.actions]
            persisted = False
            if live and run.actions:  # material = something planned/executed
                fingerprint = _material_fingerprint(run.state, exclude=frozenset())
                persisted = self._save_state(state_key, run.state, fingerprint)
            self.log.info(
                "control_loop: module=merge_lane repo=%s mode=%s "
                "planned_actions=%s top_actions=%s executed=%s persisted=%s%s",
                label,
                LIVE if live else SHADOW,
                len(run.actions),
                action_kinds[:3],
                run.executed,
                persisted,
                "" if live else ' reason="module not flipped live"',
            )

    async def _cycle_decision(self) -> None:
        """Decision-lane cycle (capability-ladder Phase 1). Quackback-only — the
        lane reads/writes board posts, which GitHubForge has no analogue for, so
        it no-ops on the github forge. Shadow plans + logs; live runs the consent
        loop through the sanitise-walled forge."""
        if not hasattr(self.forge, "list_decision_asks"):
            self.log.info(
                "control_loop: module=decision mode=%s skipped "
                '(forge has no decision lane — forge_kind != quackback)',
                self._module_mode("decision"),
            )
            return
        from wgmesh_pipeline.decision_lane import run_decision_cycle
        from wgmesh_pipeline.decision_lane.proposal_runner import build_proposal_fn

        live = self._module_live("decision")
        # The proposal recipe runner is built lazily; in shadow it is never called.
        proposal_fn = (
            build_proposal_fn(self.config) if live else (lambda post, latest: "")
        )
        result = run_decision_cycle(
            self.forge,
            self.store,
            proposal_fn,
            bot_author=self.config.decision_bot_author,
            cofounder_count=self.config.decision_cofounder_count,
            max_iterations=self.config.decision_max_iterations,
            live=live,
        )
        kinds: dict[str, int] = {}
        for action in result.planned:
            kinds[action.kind] = kinds.get(action.kind, 0) + 1
        self.log.info(
            "control_loop: module=decision mode=%s seen=%s planned=%s executed=%s%s",
            self._module_mode("decision"),
            result.seen,
            kinds,
            result.executed,
            "" if live else ' reason="module not flipped live"',
        )
