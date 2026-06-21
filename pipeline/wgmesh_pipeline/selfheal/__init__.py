"""Box-side Self-Heal: stalled-stage detection, escalation, and state building.

Port of the Actions ``pipeline-health`` workflow (cutover plan U4): the three
stale sweeps (needs-triage / copilot-triaging / approved-for-build), the
circuit breaker, the fulfilled-needs-human close, the funnel + idle signals,
the idle observation-loop dispatch, the state summary, and the
state-mutation assertion (``assert-state-mutation.sh``) all become pure
decision functions; ``run_self_heal`` is the thin runner. Semantics are
ported, not redesigned — skip ordering, substring label matching, retry /
cooldown / escalate-after-2, audit-entry shapes, and the state-file key
order are parity-tested byte-exact against the recorded
``company/pipeline-health-state.json`` on main.

Planning surface only (this phase): the runner RETURNS the state dict plus
the planned heal actions — it performs NO forge writes. Every action body /
comment must pass ``company/scripts/sanitise.sh`` before the executor
publishes it (the workflow gates every create/close on it). Failing
detections raise loudly — nothing is swallowed (institutional learning).

TODO(protocol gaps) — the Forge protocol cannot feed these sweeps, so
``SelfHealInputs`` carries plain-dict snapshots gathered elsewhere. Missing
surface (do NOT extend the protocol in this unit):
  - label-filtered issue/PR listing WITH createdAt/updatedAt — needed for
    every stale cutoff; ``list_open_issues`` has no timestamps or filters.
  - open-PR title search ("spec: Issue #N" / "impl: Issue #N") — in-progress
    skips; ``has_merged_resolution_pr`` covers only the merged-PR skip.
  - issue timeline (cross-referenced merged PRs) — needs-human signal 1.
  - cross-repo file fetch (wgmesh CLAUDE.md) — dogfood signal.
  - repository_dispatch — the idle observation-loop trigger.
  - HTTP probe of health endpoints — presence signal (boundary I/O).
"""

from wgmesh_pipeline.selfheal.conflict import plan_conflict_heal
from wgmesh_pipeline.selfheal.models import (
    ACTIVE_PIPELINE_LABELS,
    CHECK_INTERVAL_HOURS,
    CIRCUIT_MAX_CREATES,
    CIRCUIT_MAX_ERRORS,
    CONFLICT_ESCALATE_COOLDOWN_HOURS,
    ESCALATE_COOLDOWN_HOURS,
    HEAL_KIND_CHECK_REARM,
    HEAL_KIND_CONFLICT_REBASE,
    IDLE_DISPATCH_COOLDOWN_SECONDS,
    MAX_RETRIES_BEFORE_ESCALATE,
    REARM_RECHECK_COOLDOWN_HOURS,
    SUPERVISOR_DEAD_TITLE,
    CheckRearmPlan,
    ConflictHealPlan,
    HealAction,
    SelfHealInputs,
    SelfHealRun,
    SweepOutcome,
)
from wgmesh_pipeline.selfheal.rearm import plan_check_rearm
from wgmesh_pipeline.selfheal.retry_policy import Decision, apply_retry_gate
from wgmesh_pipeline.selfheal.runner import needs_human_from_forge, run_self_heal
from wgmesh_pipeline.selfheal.signals import (
    assert_state_mutation,
    build_state,
    check_funnel_signals,
    check_idle_signal,
    decide_idle_dispatch,
)
from wgmesh_pipeline.selfheal.sweeps import (
    circuit_breaker_action,
    circuit_breaker_tripped,
    sweep_needs_human,
    sweep_stale_approved,
    sweep_stale_copilot,
    sweep_stale_triage,
)

__all__ = [
    "ACTIVE_PIPELINE_LABELS",
    "CHECK_INTERVAL_HOURS",
    "CIRCUIT_MAX_CREATES",
    "CIRCUIT_MAX_ERRORS",
    "CONFLICT_ESCALATE_COOLDOWN_HOURS",
    "ESCALATE_COOLDOWN_HOURS",
    "HEAL_KIND_CHECK_REARM",
    "HEAL_KIND_CONFLICT_REBASE",
    "IDLE_DISPATCH_COOLDOWN_SECONDS",
    "MAX_RETRIES_BEFORE_ESCALATE",
    "REARM_RECHECK_COOLDOWN_HOURS",
    "SUPERVISOR_DEAD_TITLE",
    "CheckRearmPlan",
    "ConflictHealPlan",
    "Decision",
    "HealAction",
    "SelfHealInputs",
    "SelfHealRun",
    "SweepOutcome",
    "apply_retry_gate",
    "assert_state_mutation",
    "build_state",
    "check_funnel_signals",
    "check_idle_signal",
    "circuit_breaker_action",
    "circuit_breaker_tripped",
    "decide_idle_dispatch",
    "needs_human_from_forge",
    "plan_check_rearm",
    "plan_conflict_heal",
    "run_self_heal",
    "sweep_needs_human",
    "sweep_stale_approved",
    "sweep_stale_copilot",
    "sweep_stale_triage",
]
