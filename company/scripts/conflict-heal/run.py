#!/usr/bin/env python3
"""Conflict-heal orchestrator: planner (U1) → rebase executor (U3) → escalate.

Thin glue so the workflow YAML stays trivial and the orchestration is unit-
testable. Side effects (listing PRs, running the rebase script, mutating GitHub
labels/comments) are injected, so tests drive the whole loop with fakes.

Listing uses the ``gh`` CLI (number + headRefName + mergeable tri-state),
matching the ``pr-disposition.yml`` idiom and working cross-repo via ``--repo``.
The planner is pure (``plan_conflict_heal``); the rebase mutation lives in
``rebase.sh`` (bot-branch guard + ``--force-with-lease``); escalation reuses the
``needs-human`` + comment shape from ``pr-review-merge.sh``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SRC = REPO_ROOT / "pipeline"
if str(PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SRC))

from wgmesh_pipeline.selfheal import (  # noqa: E402
    CONFLICT_ESCALATE_COOLDOWN_HOURS,
    HEAL_KIND_CONFLICT_REBASE,
    plan_conflict_heal,
)
from wgmesh_pipeline.selfheal.models import shift  # noqa: E402

REBASE_SCRIPT = Path(__file__).resolve().parent / "rebase.sh"

# Injectable side effects -------------------------------------------------------
GhRun = Callable[[Sequence[str]], str]       # read-only gh, returns stdout
RebaseFn = Callable[[str, int, str], str]    # (repo, number, branch) -> OUTCOME line
GhMutate = Callable[[Sequence[str]], None]   # write gh (edit/comment)


def _real_gh_run(args: Sequence[str]) -> str:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    ).stdout


def _real_gh_mutate(args: Sequence[str]) -> None:
    subprocess.run(["gh", *args], check=True)


def _real_rebase(repo: str, number: int, branch: str) -> str:
    out = subprocess.run(
        ["bash", str(REBASE_SCRIPT), repo, str(number), branch],
        check=True, capture_output=True, text=True,
    ).stdout
    return out.strip().splitlines()[-1] if out.strip() else ""


# Pure helpers ------------------------------------------------------------------

def normalize_mergeable(value: Any) -> str | None:
    """gh reports MERGEABLE / CONFLICTING / UNKNOWN; map UNKNOWN (and anything
    not yet computed) to None so the planner skips it this cycle."""
    return value if value in ("MERGEABLE", "CONFLICTING") else None


def list_open_prs(target_repo: str, gh_run: GhRun) -> list[dict[str, Any]]:
    """Open PRs as planner-ready dicts: number, headRefName, mergeable (tri)."""
    raw = gh_run([
        "pr", "list", "--repo", target_repo, "--state", "open",
        "--limit", "200",
        "--json", "number,headRefName,mergeable",
    ])
    prs = json.loads(raw) if raw.strip() else []
    return [
        {
            "number": int(pr["number"]),
            "headRefName": pr.get("headRefName") or "",
            "mergeable": normalize_mergeable(pr.get("mergeable")),
        }
        for pr in prs
    ]


def parse_outcome(line: str) -> str:
    """Extract OUTCOME=<slug> from a rebase.sh result line."""
    for token in line.split():
        if token.startswith("OUTCOME="):
            return token.split("=", 1)[1]
    return "unknown"


def _escalate(
    number: int,
    comment: str,
    *,
    gh_mutate: GhMutate,
    target_repo: str,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"DRY_RUN escalate PR #{number}: would add needs-human + comment")
        return
    gh_mutate(["pr", "edit", str(number), "--repo", target_repo, "--add-label", "needs-human"])
    gh_mutate(["pr", "comment", str(number), "--repo", target_repo, "--body", comment])


# Orchestration -----------------------------------------------------------------

def run_conflict_heal(
    target_repo: str,
    state: Mapping[str, Any],
    now: str,
    *,
    dry_run: bool,
    gh_run: GhRun,
    rebase_fn: RebaseFn,
    gh_mutate: GhMutate,
    escalate_cooldown_hours: float = CONFLICT_ESCALATE_COOLDOWN_HOURS,
) -> dict[str, Any]:
    """Plan + execute one conflict-heal cycle, returning the new state dict.

    R5: a clean rebase RESETS the PR's retry entry; only rebase *failures*
    increment toward the cap. R6: an empty-after-rebase PR escalates (content
    already in main) instead of pushing. dry_run makes zero mutations and is
    surfaced by the caller to skip the state write.
    """
    prs = list_open_prs(target_repo, gh_run)
    tracker_in: Mapping[str, Any] = dict(state.get("retry_tracker") or {})
    plan = plan_conflict_heal(
        prs, tracker_in, now,
        dry_run=dry_run, escalate_cooldown_hours=escalate_cooldown_hours,
    )
    branch_by_number = {pr["number"]: pr["headRefName"] for pr in prs}
    tracker: dict[str, Any] = dict(plan.tracker)

    for action in plan.actions:
        number = int(action.number)  # type: ignore[arg-type]
        key = f"pr-{number}"
        if action.kind == "escalate":
            # Planner already set the cooldown in plan.tracker; just publish.
            _escalate(
                number, action.comment or "Conflict-heal escalation.",
                gh_mutate=gh_mutate, target_repo=target_repo, dry_run=dry_run,
            )
            continue
        if action.kind != HEAL_KIND_CONFLICT_REBASE:
            continue
        branch = branch_by_number.get(number, "")
        if dry_run:
            print(f"DRY_RUN rebase PR #{number} ({branch}): would rebase onto main")
            continue
        outcome = parse_outcome(rebase_fn(target_repo, number, branch))
        entry = dict(tracker.get(key) or {})
        if outcome == "rebased":
            tracker.pop(key, None)  # R5: clean reset
        elif outcome == "empty":
            _escalate(
                number,
                "Conflict-heal: this PR's content already merged to main "
                "(empty after rebase). A human should close it.",
                gh_mutate=gh_mutate, target_repo=target_repo, dry_run=dry_run,
            )
            tracker[key] = {**entry, "cooldown_until": shift(now, hours=escalate_cooldown_hours)}
        elif outcome == "conflict":
            retries = int(entry.get("retries") or 0) + 1
            tracker[key] = {**entry, "retries": retries, "last_retry": now,
                            "action": HEAL_KIND_CONFLICT_REBASE}
        else:  # skipped / unknown — leave tracker untouched, log loudly
            print(f"::warning::rebase PR #{number} returned OUTCOME={outcome}; no tracker change")

    # NB: deliberately no timestamp in the persisted state — the commit gate is
    # a byte diff, so an unchanged tracker must produce an identical file (no
    # churn commit, per the idempotency requirement).
    return {**state, "retry_tracker": tracker}


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Conflict-heal orchestrator")
    parser.add_argument("--target-repo", default=os.environ.get("TARGET_REPO", ""))
    parser.add_argument("--state-file", default=os.environ.get(
        "CONFLICT_HEAL_STATE", "company/conflict-heal-state.json"))
    parser.add_argument("--now", default=os.environ.get("NOW", ""))
    parser.add_argument("--dry-run", action="store_true",
                        default=os.environ.get("DRY_RUN", "false") == "true")
    args = parser.parse_args(argv)

    if not args.target_repo:
        parser.error("TARGET_REPO (or --target-repo) is required")
    now = args.now
    if not now:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    state_path = Path(args.state_file)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"retry_tracker": {}}

    new_state = run_conflict_heal(
        args.target_repo, state, now,
        dry_run=args.dry_run,
        gh_run=_real_gh_run, rebase_fn=_real_rebase, gh_mutate=_real_gh_mutate,
    )

    if args.dry_run:
        print("DRY_RUN: no state written.")
    else:
        _write_state(state_path, new_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
