"""Control-Loop scheduler tests (cutover Phase B/C, shadow-only).

These pin the zero-blast-radius contract: each enabled module fires on its
cadence, NO forge writes or store persistence happen in shadow, one planner
crashing does not stop its siblings or the scheduler, stop cancels promptly,
the observation/strategy_audit slots log their skip reason, and live mode is
forced to shadow with a warning.

Planners are injected as spies so tests never hit the real forge/LLM. The
forge spy records every method call and raises if any *write* method is
touched (the lowest-boundary check that shadow truly writes nothing). No
mutable tree-state file is read (frozen inputs only — PR #1691 lesson).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import pytest

from wgmesh_pipeline import control_loop as cl
from wgmesh_pipeline.config import Config, load_config
from wgmesh_pipeline.control_loop import ControlLoopScheduler
from wgmesh_pipeline.selfheal import SelfHealInputs, SelfHealRun
from wgmesh_pipeline.supervisor import RankResult, SupervisorRankRun


# --- frozen fakes -----------------------------------------------------------

_WRITE_METHODS = frozenset({
    "add_label", "remove_label", "comment", "create_pr", "update_pr_body",
    "merge_pr", "push_branch", "approve_pr",
})


class SpyForge:
    """Records read calls; raises on ANY write method (shadow must not write)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.write_calls: list[str] = []

    def __getattr__(self, name: str):
        def method(*args, **kwargs):
            self.calls.append(name)
            if name in _WRITE_METHODS:
                self.write_calls.append(name)
                raise AssertionError(f"shadow scheduler called forge write {name!r}")
            if name == "list_open_issues":
                return []
            return None
        return method


class SpyStore:
    """Records any method call; the scheduler must touch none in shadow."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def method(*args, **kwargs):
            self.calls.append(name)
            return None
        return method


def _empty_rank_run() -> SupervisorRankRun:
    result = RankResult(generated_at="2026-06-13T00:00:00Z", top=(), stage_summary={}, unknown=())
    return SupervisorRankRun(result=result, state={}, material_changed=False, rank_changed=False)


def _empty_selfheal_run() -> SelfHealRun:
    return SelfHealRun(
        state={}, actions=(), audit=(), circuit_breaker_tripped=False, mutation_asserted=True,
    )


@dataclass
class Spy:
    """A counting spy for an injected planner; returns a fixed result."""

    result: object
    raises: bool = False
    calls: int = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.raises:
            raise RuntimeError("planner boom")
        return self.result


def _config(**overrides) -> Config:
    base = dict(
        target_repo="atvirokodosprendimai/wgmesh",
        mode="shadow",
        database_mode="local",
        control_loop_enabled=True,
        control_loop_mode="shadow",
        # tiny cadences so tests fire fast
        selfheal_interval_seconds=1,
        supervisor_interval_seconds=1,
        observation_interval_seconds=1,
        strategy_audit_interval_seconds=1,
    )
    base.update(overrides)
    return Config(**base)


async def _run_briefly(scheduler: ControlLoopScheduler, *, seconds: float = 0.05) -> None:
    stop = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(seconds)
        stop.set()

    await asyncio.wait_for(
        asyncio.gather(scheduler.run(stop), stopper()), timeout=5.0
    )


# --- tests ------------------------------------------------------------------

def test_each_enabled_planner_fires_at_least_once() -> None:
    sup = Spy(_empty_rank_run())
    heal = Spy(_empty_selfheal_run())
    sched = ControlLoopScheduler(
        config=_config(selfheal_interval_seconds=0.01, supervisor_interval_seconds=0.01,
                       observation_interval_seconds=0.01, strategy_audit_interval_seconds=0.01),
        forge=SpyForge(), store=SpyStore(),
        supervisor_planner=sup, selfheal_planner=heal,
    )
    asyncio.run(_run_briefly(sched))
    assert sup.calls >= 1, "supervisor planner never fired"
    assert heal.calls >= 1, "selfheal planner never fired"


def test_shadow_performs_no_forge_writes_or_store_writes() -> None:
    forge = SpyForge()
    store = SpyStore()
    sched = ControlLoopScheduler(
        config=_config(selfheal_interval_seconds=0.01, supervisor_interval_seconds=0.01),
        forge=forge, store=store,
        supervisor_planner=Spy(_empty_rank_run()), selfheal_planner=Spy(_empty_selfheal_run()),
    )
    asyncio.run(_run_briefly(sched))
    assert forge.write_calls == [], f"shadow wrote to forge: {forge.write_calls}"
    assert store.calls == [], f"shadow persisted to store: {store.calls}"


def test_one_planner_raising_does_not_stop_siblings_or_scheduler() -> None:
    boom = Spy(_empty_rank_run(), raises=True)   # supervisor crashes every cycle
    heal = Spy(_empty_selfheal_run())            # sibling must keep firing
    sched = ControlLoopScheduler(
        config=_config(selfheal_interval_seconds=0.01, supervisor_interval_seconds=0.01),
        forge=SpyForge(), store=SpyStore(),
        supervisor_planner=boom, selfheal_planner=heal,
    )
    asyncio.run(_run_briefly(sched, seconds=0.08))
    assert boom.calls >= 2, "crashing planner stopped retrying — task died"
    assert heal.calls >= 2, "sibling stopped firing when supervisor crashed"


def test_stop_event_cancels_all_tasks_promptly() -> None:
    sched = ControlLoopScheduler(
        config=_config(selfheal_interval_seconds=100, supervisor_interval_seconds=100,
                       observation_interval_seconds=100, strategy_audit_interval_seconds=100),
        forge=SpyForge(), store=SpyStore(),
        supervisor_planner=Spy(_empty_rank_run()), selfheal_planner=Spy(_empty_selfheal_run()),
    )
    # Long intervals: run() must still return promptly once stop is set, proving
    # the wait is interruptible (not blocked on the 100s timeout).
    asyncio.run(_run_briefly(sched, seconds=0.02))


def test_observation_and_strategy_audit_slots_log_skip_reason(caplog) -> None:
    sched = ControlLoopScheduler(
        config=_config(observation_interval_seconds=0.01, strategy_audit_interval_seconds=0.01),
        forge=SpyForge(), store=SpyStore(),
        supervisor_planner=Spy(_empty_rank_run()), selfheal_planner=Spy(_empty_selfheal_run()),
    )
    with caplog.at_level(logging.INFO, logger="wgmesh_pipeline.control_loop"):
        asyncio.run(_run_briefly(sched))
    text = caplog.text
    assert "module=observation" in text and "LLM assessment input not yet wired" in text
    assert "module=strategy_audit" in text and "live metrics gather not yet wired" in text


def test_live_mode_forced_to_shadow_with_warning_no_writes(caplog) -> None:
    forge = SpyForge()
    with caplog.at_level(logging.WARNING, logger="wgmesh_pipeline.control_loop"):
        sched = ControlLoopScheduler(
            config=_config(control_loop_mode="live", selfheal_interval_seconds=0.01,
                           supervisor_interval_seconds=0.01),
            forge=forge, store=SpyStore(),
            supervisor_planner=Spy(_empty_rank_run()), selfheal_planner=Spy(_empty_selfheal_run()),
        )
        asyncio.run(_run_briefly(sched))
    assert "FORCING shadow" in caplog.text
    assert forge.write_calls == []


def test_real_planners_are_the_defaults() -> None:
    from wgmesh_pipeline.selfheal import run_self_heal
    from wgmesh_pipeline.supervisor import run_supervisor_rank

    sched = ControlLoopScheduler(config=_config(), forge=SpyForge(), store=SpyStore())
    assert sched.supervisor_planner is run_supervisor_rank
    assert sched.selfheal_planner is run_self_heal


def test_real_planners_run_against_forge_without_writing() -> None:
    # Smoke: with the real (un-injected) planners over a SpyForge, a shadow run
    # gathers via list_open_issues and writes nothing (proves degraded gather +
    # zero-write contract end-to-end, not just with spies).
    forge = SpyForge()
    sched = ControlLoopScheduler(
        config=_config(selfheal_interval_seconds=0.01, supervisor_interval_seconds=0.01,
                       observation_interval_seconds=100, strategy_audit_interval_seconds=100),
        forge=forge, store=SpyStore(),
    )
    asyncio.run(_run_briefly(sched))
    assert forge.write_calls == []
    assert "list_open_issues" in forge.calls


# --- config env parsing -----------------------------------------------------

def _base_env(**extra) -> dict[str, str]:
    env = {"TARGET_REPO": "atvirokodosprendimai/wgmesh", "DATABASE_MODE": "local"}
    env.update(extra)
    return env


def test_config_defaults_control_loop_disabled_shadow() -> None:
    cfg = load_config(_base_env())
    assert cfg.control_loop_enabled is False
    assert cfg.control_loop_mode == "shadow"
    assert cfg.selfheal_interval_seconds == 1800
    assert cfg.supervisor_interval_seconds == 14400
    assert cfg.observation_interval_seconds == 28800
    assert cfg.strategy_audit_interval_seconds == 86400


def test_config_parses_control_loop_env() -> None:
    cfg = load_config(_base_env(
        CONTROL_LOOP_ENABLED="true",
        CONTROL_LOOP_MODE="live",
        SELFHEAL_INTERVAL_SECONDS="60",
        SUPERVISOR_INTERVAL_SECONDS="120",
        OBSERVATION_INTERVAL_SECONDS="180",
        STRATEGY_AUDIT_INTERVAL_SECONDS="240",
    ))
    assert cfg.control_loop_enabled is True
    assert cfg.control_loop_mode == "live"  # honored in config; scheduler forces shadow
    assert cfg.selfheal_interval_seconds == 60
    assert cfg.supervisor_interval_seconds == 120
    assert cfg.observation_interval_seconds == 180
    assert cfg.strategy_audit_interval_seconds == 240


def test_config_rejects_bad_control_loop_mode() -> None:
    with pytest.raises(ValueError, match="CONTROL_LOOP_MODE"):
        load_config(_base_env(CONTROL_LOOP_MODE="bogus"))


def test_config_truthy_variants() -> None:
    for raw in ("1", "true", "YES", "On"):
        assert load_config(_base_env(CONTROL_LOOP_ENABLED=raw)).control_loop_enabled is True
    for raw in ("0", "false", "", "no"):
        assert load_config(_base_env(CONTROL_LOOP_ENABLED=raw)).control_loop_enabled is False
