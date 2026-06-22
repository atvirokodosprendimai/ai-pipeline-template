"""Self-Heal dataclasses, constants, and shared pure helpers (cutover U4).

Constants mirror the ``pipeline-health`` workflow's hard-coded values; the
dataclasses are the planning surface — no forge writes happen here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

TARGET_REPO_NAME = "wgmesh"
MAX_RETRIES_BEFORE_ESCALATE = 2
CIRCUIT_MAX_CREATES = 10
CIRCUIT_MAX_ERRORS = 5
ESCALATE_COOLDOWN_HOURS = 24
# Conflict-heal: a genuinely unresolvable rebase rests longer before re-trying
# (it almost always needs a human), so its escalate cooldown is wider than the
# stale sweeps'. The retry cap is shared (MAX_RETRIES_BEFORE_ESCALATE).
CONFLICT_ESCALATE_COOLDOWN_HOURS = 72
HEAL_KIND_CONFLICT_REBASE = "conflict_rebase"
# Check-rearm: a MERGEABLE bot PR whose required judge check never ran (it
# predates the lane, so no pull_request event ever fired it) is permanently
# pending, never red. We re-arm it (enable auto-merge + push an empty commit to
# fire the judge). After a re-arm we wait one cron cycle before re-checking, so
# a single tick can't thrash a branch while the judge runs. The retry cap is
# shared (MAX_RETRIES_BEFORE_ESCALATE); the escalate cooldown reuses the
# conflict value (a PR that can't be armed in 2 tries needs a human).
HEAL_KIND_CHECK_REARM = "check_rearm"
REARM_RECHECK_COOLDOWN_HOURS = 6
# Stale-base-heal: a MERGEABLE bot PR (no conflict) can still be RED because its
# branch was cut before a since-merged fix to main — its tree is stale and the
# failing check is already resolved on current main. conflict-heal only rebases
# CONFLICTING PRs, so these stay frozen. We rebase them onto main so checks
# re-run against the fixed tree. Only ever touch a PR that is behind main AND has
# a failing check (a green-or-current PR needs no force-push — thrash guard). If
# it still fails after the shared retry cap, the failure is in the PR's own diff,
# not a stale base → escalate. Cooldown reuses the conflict value.
HEAL_KIND_STALE_BASE_REBASE = "stale_base_rebase"
IDLE_DISPATCH_COOLDOWN_SECONDS = 6 * 60 * 60
CHECK_INTERVAL_HOURS = 0.5
ACTIVE_PIPELINE_LABELS = (
    "needs-triage", "copilot-triaging", "copilot-revising",
    "approved-for-build", "goose-implementation",
)
SUPERVISOR_DEAD_TITLE = "supervisor-dead: pipeline-health frozen"


@dataclass(frozen=True)
class HealAction:
    """One planned heal write. ``body``/``comment`` MUST pass the sanitise
    gate before the executor publishes them (workflow parity)."""

    kind: str  # audit action name: retrigger_* / escalate / close_needs_human / ...
    number: int | None = None
    target: str = "issue"  # "issue" | "pr" | "repo"
    remove_label: str | None = None
    add_label: str | None = None
    title: str | None = None
    body: str | None = None
    comment: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class SweepOutcome:
    """Counters + planned actions from one detector (mirrors the per-step
    ``local_*`` counters the workflow accumulates into GITHUB_ENV)."""

    actions: tuple[HealAction, ...] = ()
    audit: tuple[dict[str, Any], ...] = ()
    retry_tracker: Mapping[str, Any] = field(default_factory=dict)
    stale_found: int = 0
    actions_taken: int = 0
    errors: int = 0
    issues_created: int = 0
    closed: int = 0


@dataclass(frozen=True)
class SelfHealInputs:
    """Plain-dict inputs replacing the workflow's label-filtered queries
    (see protocol gaps in the package docstring). Items carry the query JSON
    shapes: number, title, createdAt/updatedAt, labels (names or
    ``{"name": …}``)."""

    now: str
    run_id: str = "local"
    previous_state: Mapping[str, Any] = field(default_factory=dict)
    stale_triage_issues: tuple[Mapping[str, Any], ...] = ()
    stale_copilot_issues: tuple[Mapping[str, Any], ...] = ()
    stale_approved_prs: tuple[Mapping[str, Any], ...] = ()
    needs_human_issues: tuple[Mapping[str, Any], ...] | None = None
    merged_resolution_issues: frozenset[int] = frozenset()
    open_spec_pr_issues: frozenset[int] = frozenset()
    open_impl_pr_issues: frozenset[int] = frozenset()
    # Count of merged IMPL/FIX resolution PRs linked to each issue. FALSE-
    # COMPLETION GUARD: the gather MUST filter cross-referenced PR titles to
    # ^(impl|fix): — a merged spec:/heal:/loop: PR is NOT resolution. Counting
    # spec merges falsely closed #539/#573 (legacy pipeline-health bug fixed
    # 2026-06-13); this contract keeps the on-box gather correct by design.
    linked_merged_pr_counts: Mapping[int, int] = field(default_factory=dict)
    loop_state: Mapping[str, Any] = field(default_factory=dict)
    costs: Mapping[str, Any] = field(default_factory=dict)
    endpoints: tuple[Mapping[str, Any], ...] = ()  # {name, url, status}
    claude_md_text: str | None = None
    open_prs: int = 0
    open_issues: tuple[Mapping[str, Any], ...] = ()
    cutoff_override_minutes: int | None = None
    signals_now: str | None = None  # separate step clock; defaults to ``now``


@dataclass(frozen=True)
class SelfHealRun:
    """Runner outcome: planned actions + the state dict the caller may
    persist (after the sanitise gate), plus the mutation-assertion verdict."""

    state: dict[str, Any]
    actions: tuple[HealAction, ...]
    audit: tuple[dict[str, Any], ...]
    circuit_breaker_tripped: bool
    mutation_asserted: bool


@dataclass(frozen=True)
class ConflictHealPlan:
    """Result of the pure conflict-heal planner: the planned ``conflict_rebase``
    / ``escalate`` actions plus the retry tracker the executor persists. The
    planner does NOT increment a rebase attempt — the executor reports the
    outcome and the *next* cycle's tracker reflects it (R5)."""

    actions: tuple[HealAction, ...] = ()
    tracker: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False


@dataclass(frozen=True)
class CheckRearmPlan:
    """Result of the pure check-rearm planner: the planned ``check_rearm`` /
    ``escalate`` actions plus the retry tracker the executor persists. Like the
    conflict planner, it does NOT record the re-arm attempt — the executor
    reports the outcome and the next cycle's tracker reflects it."""

    actions: tuple[HealAction, ...] = ()
    tracker: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False


@dataclass(frozen=True)
class StaleBaseHealPlan:
    """Result of the pure stale-base-heal planner: the planned
    ``stale_base_rebase`` / ``escalate`` actions plus the retry tracker the
    executor persists. Like the conflict planner, it does NOT increment a rebase
    attempt — the executor reports the outcome and the next cycle's tracker
    reflects it (R5: clean rebase resets, failure increments)."""

    actions: tuple[HealAction, ...] = ()
    tracker: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def shift(now: str, *, hours: float = 0, minutes: float = 0) -> str:
    return iso(parse_iso(now) + timedelta(hours=hours, minutes=minutes))


def labels_joined(item: Mapping[str, Any]) -> str:
    """Comma-joined label names — the workflow greps this string, so all
    label checks downstream are SUBSTRING matches (ported as-is)."""
    names = []
    for label in item.get("labels") or []:
        names.append(str(label.get("name")) if isinstance(label, Mapping) else str(label))
    return ",".join(names)


def first_timestamp(item: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if item.get(key):
            return str(item[key])
    return ""


def audit_entry(now: str, run_id: str, action: str, number: int | None, reason: str,
                retry_count: int | None, **extra: Any) -> dict[str, Any]:
    """Audit-log entry, key order byte-compatible with the workflow's jq -nc."""
    return {
        "timestamp": now, "run_id": run_id, "action": action,
        "issue_number": number, "target_repo": TARGET_REPO_NAME,
        "reason": reason, "outcome": "success", "retry_count": retry_count,
        **extra,
    }


def tracker_entry(tracker: Mapping[str, Any], key: str) -> dict[str, Any]:
    entry = tracker.get(key) or {}
    if not isinstance(entry, Mapping):  # fail loudly, never swallow
        raise ValueError(f"malformed retry_tracker entry for {key!r}: {entry!r}")
    return dict(entry)
