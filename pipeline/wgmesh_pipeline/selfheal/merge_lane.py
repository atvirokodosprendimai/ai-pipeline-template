"""Box-native merge-lane-heal module (U2).

Replaces the ``conflict-heal.yml`` Actions cron on the box control loop
(project_actions_cicd_only_retarget). Runs the same three-pass logic as the
cron but via the forge client instead of the ``gh`` CLI:

  Pass A — CONFLICTING bot PRs → rebase onto main (``conflict_rebase``).
  Pass B — MERGEABLE bot fix PRs with absent required judge check → re-arm
           (enable auto-merge + push an empty commit, ``check_rearm``).
  Pass C — MERGEABLE bot PRs behind main with no failing check → rebase onto
           main (``stale_base_rebase``).

A PR actioned by an earlier pass is not double-actioned by a later one (set
membership guard on ``actioned`` PR numbers).

Side effects are injected (``forge`` duck-typed, ``rebase_fn`` injectable)
so all logic is unit-testable without real network or subprocess calls.

The module is INERT until ``MERGE_LANE_HEAL_LIVE=true`` (U4 cutover); shadow
mode (``live=False``) plans actions and returns the would-be state but
executes nothing — zero forge mutations.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from wgmesh_pipeline.selfheal.conflict import plan_conflict_heal
from wgmesh_pipeline.selfheal.models import (
    CONFLICT_ESCALATE_COOLDOWN_HOURS,
    HEAL_KIND_CHECK_REARM,
    HEAL_KIND_CONFLICT_REBASE,
    HEAL_KIND_STALE_BASE_REBASE,
    REARM_RECHECK_COOLDOWN_HOURS,
    HealAction,
    MergeLaneHealRun,
    shift,
    tracker_entry,
)
from wgmesh_pipeline.selfheal.rearm import DEFAULT_REQUIRED_CONTEXT, plan_check_rearm
from wgmesh_pipeline.selfheal.stale_base import plan_stale_base_heal

# Injected callable types (duck-typed, no concrete imports)
RebaseFn = Callable[[str, int, str], str]   # (repo, pr_number, branch) -> OUTCOME= line

# Real rebase implementation: wraps company/scripts/conflict-heal/rebase.sh.
# Injected by the caller so tests can swap in a fake.
_REBASE_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "company" / "scripts" / "conflict-heal" / "rebase.sh"
)

BOT_BRANCH_PREFIX = "bot/"
MERGEABLE = "MERGEABLE"
CONFLICTING = "CONFLICTING"


def _real_rebase(repo: str, number: int, branch: str) -> str:
    """Shell out to rebase.sh (bot-branch guard + --force-with-lease).
    Returns the last non-empty stdout line which contains ``OUTCOME=...``."""
    out = subprocess.run(
        ["bash", str(_REBASE_SCRIPT), repo, str(number), branch],
        check=True, capture_output=True, text=True,
    ).stdout
    lines = [l for l in out.splitlines() if l.strip()]
    return lines[-1] if lines else ""


def _parse_outcome(line: str) -> str:
    """Extract ``OUTCOME=<slug>`` from a rebase.sh result line."""
    for token in line.split():
        if token.startswith("OUTCOME="):
            return token.split("=", 1)[1]
    return "unknown"


def run_merge_lane_heal(
    forge: Any,
    state: Mapping[str, Any],
    now: str,
    *,
    live: bool,
    rebase_fn: RebaseFn = _real_rebase,
    repo_label: str = "seed",
    escalate_cooldown_hours: float = CONFLICT_ESCALATE_COOLDOWN_HOURS,
    required_context: str = DEFAULT_REQUIRED_CONTEXT,
) -> MergeLaneHealRun:
    """Plan (and, when ``live``, execute) one merge-lane-heal cycle.

    Gather
    ------
    List all open PRs via ``forge.list_open_pull_requests()`` → ``[{number,
    headRefName}]``. For each bot/* PR:
      - resolve ``mergeable`` via ``forge.get_pr_mergeable(number)``
      - for MERGEABLE-only: resolve ``behindBy`` + ``hasFailingCheck``

    Plan (pure, A→B→C)
    ------------------
    Run the three pure planners in order, collecting a combined action list.
    Track which PR numbers have already been actioned; later passes skip
    already-actioned numbers (no double-action).

    Execute (only when ``live`` is True)
    ------------------------------------
    For each action apply the forge mutation + ``rebase_fn``. Mirrors the
    outcome handling in ``conflict-heal/run.py`` and ``check-rearm/run.py``:
      - ``conflict_rebase`` / ``stale_base_rebase``:
          rebased → pop tracker (clean reset)
          empty   → escalate (content already in main) + cooldown
          conflict → increment retries
      - ``check_rearm``:
          rearmed → record attempt + recheck cooldown
          error   → record attempt + recheck cooldown
      - ``escalate``: add needs-human label + comment

    Shadow
    ------
    When ``live`` is False, execute NOTHING — return the planned actions and
    the tracker that *would* have been written. The caller decides whether to
    persist state (shadow mode: skip).

    Returns a ``MergeLaneHealRun`` with the planned actions, the new state
    dict, the executed count, and the ``dry_run`` flag (inverted ``live``).
    """
    # ── Gather ────────────────────────────────────────────────────────────────
    raw_prs: list[dict[str, Any]] = forge.list_open_pull_requests()

    # Build enriched PR dicts for the planners.  Only resolve the expensive
    # per-PR mergeability/behindBy/hasFailingCheck for bot/* branches.
    prs_for_conflict: list[dict[str, Any]] = []
    prs_for_rearm: list[dict[str, Any]] = []
    prs_for_stale: list[dict[str, Any]] = []

    for raw in raw_prs:
        number: int = raw["number"]
        head: str = raw.get("headRefName") or ""
        if not head.startswith(BOT_BRANCH_PREFIX):
            continue  # never touch human PRs in any pass

        mergeable = forge.get_pr_mergeable(number)

        # Pass A input: conflict planner needs number + headRefName + mergeable
        prs_for_conflict.append({
            "number": number,
            "headRefName": head,
            "mergeable": mergeable,
        })

        # Passes B+C only care about MERGEABLE PRs
        if mergeable != MERGEABLE:
            continue

        behind_by: int = forge.compare_behind_by(head)
        has_failing: bool = forge.pr_has_failing_check(number)

        # Pass B input: rearm planner needs number + headRefName + mergeable +
        # title + isDraft + present_contexts.  We don't carry title/isDraft here
        # (the box gather doesn't fetch them); use empty title so the FIX_TITLE
        # prefix check in the planner filters them.  The planner only acts on
        # "fix: Issue #" PRs, and title is available if needed in a future
        # revision; for now pass it through as an empty default — the rearm
        # planner skips non-fix-titled PRs, which is correct.
        prs_for_rearm.append({
            "number": number,
            "headRefName": head,
            "mergeable": mergeable,
            "title": raw.get("title", ""),
            "isDraft": raw.get("isDraft", False),
            "present_contexts": raw.get("present_contexts", set()),
        })

        # Pass C input: stale_base planner needs number + headRefName +
        # mergeable + behindBy + hasFailingCheck
        prs_for_stale.append({
            "number": number,
            "headRefName": head,
            "mergeable": mergeable,
            "behindBy": behind_by,
            "hasFailingCheck": has_failing,
        })

    # ── Plan (A→B→C, with double-action guard) ────────────────────────────────
    tracker_in: dict[str, Any] = dict(state.get("retry_tracker") or {})

    plan_a = plan_conflict_heal(
        prs_for_conflict, tracker_in, now,
        dry_run=not live,
        escalate_cooldown_hours=escalate_cooldown_hours,
    )
    actioned: set[int] = {
        int(a.number) for a in plan_a.actions if a.number is not None
    }

    plan_b = plan_check_rearm(
        prs_for_rearm, plan_a.tracker, now,
        required_context=required_context,
        dry_run=not live,
        escalate_cooldown_hours=escalate_cooldown_hours,
    )
    # Drop Pass B actions for PRs already actioned by Pass A
    b_actions = tuple(
        a for a in plan_b.actions
        if a.number is None or int(a.number) not in actioned
    )
    actioned.update(
        int(a.number) for a in b_actions if a.number is not None
    )
    # Carry forward the tracker from B (which already incorporates A's tracker)
    # but rebuild it only for the non-dropped actions
    tracker_after_b = dict(plan_b.tracker)

    plan_c = plan_stale_base_heal(
        prs_for_stale, tracker_after_b, now,
        dry_run=not live,
        escalate_cooldown_hours=escalate_cooldown_hours,
    )
    # Drop Pass C actions for PRs already actioned by Pass A or B
    c_actions = tuple(
        a for a in plan_c.actions
        if a.number is None or int(a.number) not in actioned
    )

    all_actions: tuple[HealAction, ...] = (
        plan_a.actions + b_actions + c_actions
    )
    # The final tracker from Pass C incorporates all three passes
    tracker_out: dict[str, Any] = dict(plan_c.tracker)

    new_state: dict[str, Any] = {"retry_tracker": tracker_out}
    executed = 0

    if not live:
        # Shadow: return planned actions + would-be state, execute nothing.
        return MergeLaneHealRun(
            actions=all_actions,
            state=new_state,
            executed=0,
            dry_run=True,
        )

    # ── Execute ───────────────────────────────────────────────────────────────
    for action in all_actions:
        number = int(action.number) if action.number is not None else None
        key = f"pr-{number}" if number is not None else None
        entry = tracker_entry(tracker_out, key) if key else {}

        if action.kind == "escalate":
            _escalate(forge, number, action.comment or "Merge-lane heal escalation.")
            executed += 1
            continue

        if action.kind in (HEAL_KIND_CONFLICT_REBASE, HEAL_KIND_STALE_BASE_REBASE):
            assert number is not None and key is not None
            # Resolve branch name from the gathered PR list
            head = _head_for(prs_for_conflict + prs_for_stale, number)
            # Forge doesn't carry a repo slug — build from config if available
            repo = getattr(getattr(forge, "config", None), "target_repo", "")
            outcome = _parse_outcome(rebase_fn(repo, number, head))
            if outcome == "rebased":
                tracker_out.pop(key, None)   # R5: clean reset on success
            elif outcome == "empty":
                _escalate(
                    forge, number,
                    "Merge-lane heal: this PR's content already merged to main "
                    "(empty after rebase). A human should close it.",
                )
                tracker_out[key] = {
                    **entry, "cooldown_until": shift(now, hours=escalate_cooldown_hours)
                }
            elif outcome == "conflict":
                retries = int(entry.get("retries") or 0) + 1
                tracker_out[key] = {
                    **entry, "retries": retries, "last_retry": now,
                    "action": action.kind,
                }
            else:
                print(
                    f"::warning::merge-lane-heal rebase PR #{number} "
                    f"returned OUTCOME={outcome}; no tracker change"
                )
            executed += 1
            continue

        if action.kind == HEAL_KIND_CHECK_REARM:
            assert number is not None and key is not None
            head = _head_for(prs_for_rearm, number)
            repo = getattr(getattr(forge, "config", None), "target_repo", "")
            # KTD2: enable auto-merge FIRST, then push the empty commit
            forge.enable_auto_merge(number)
            outcome = _parse_outcome(rebase_fn(repo, number, head))
            if outcome in ("rearmed", "error"):
                retries = int(entry.get("retries") or 0) + 1
                tracker_out[key] = {
                    **entry, "retries": retries, "last_retry": now,
                    "action": HEAL_KIND_CHECK_REARM,
                    "cooldown_until": shift(now, hours=REARM_RECHECK_COOLDOWN_HOURS),
                }
            else:
                print(
                    f"::warning::merge-lane-heal re-arm PR #{number} "
                    f"returned OUTCOME={outcome}; no tracker change"
                )
            executed += 1
            continue

    new_state = {"retry_tracker": tracker_out}
    return MergeLaneHealRun(
        actions=all_actions,
        state=new_state,
        executed=executed,
        dry_run=False,
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _escalate(forge: Any, number: int | None, comment: str) -> None:
    """Add needs-human label + comment on a PR via the forge client."""
    if number is None:
        return
    forge.add_label(number, "needs-human")
    forge.comment(number, comment)


def _head_for(prs: list[dict[str, Any]], number: int) -> str:
    """Return headRefName for ``number`` from a pre-gathered PR list, or ''."""
    for pr in prs:
        if int(pr["number"]) == number:
            return str(pr.get("headRefName") or "")
    return ""
