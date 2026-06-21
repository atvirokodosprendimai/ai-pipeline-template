#!/usr/bin/env python3
"""Check-rearm orchestrator: planner → enable-auto-merge + re-arm → escalate.

The MERGEABLE-but-unjudged sibling of ``conflict-heal/run.py``. A bot ``fix:``
PR can sit MERGEABLE + all-produced-checks-green yet blocked forever because the
required ``impl-judge`` check was never produced (the PR predates the judge
workflow, so no ``pull_request`` event ever fired it — an absent required check
is permanently pending, not red). This loop, per repo:

  1. lists open PRs via ``gh`` (number, headRefName, mergeable, title, isDraft,
     statusCheckRollup) — one call, cross-repo via ``--repo`` (no per-PR fetch);
  2. resolves each PR's present check/status contexts from the rollup;
  3. plans re-arm/escalate via the pure ``plan_check_rearm``;
  4. for each re-arm: ENABLES AUTO-MERGE FIRST (the standing backlog has
     ``autoMergeRequest: null`` — it predates the box's gate.py auto-merge
     wiring, so re-arming the check alone would leave a green-but-idle PR), THEN
     pushes an empty commit (``rearm.sh``) to fire the judge. Once the judge +
     build + status are green, GitHub merges — no approval, no reviewer PAT.

Side effects (listing, enabling auto-merge, running the re-arm script, escalate
mutations) are injected, so tests drive the whole loop with fakes. The planner
is pure; the git mutation lives in ``rearm.sh`` (bot-branch guard + empty commit
+ normal push); escalation reuses the ``needs-human`` + comment shape.

NOTE (plan U2 deviation): the plan proposed a ``client.list_pr_check_contexts``
Python method, but this orchestrator follows the conflict-heal idiom (``gh`` CLI,
no Python client), so present contexts come from ``gh``'s ``statusCheckRollup``
in the single list call instead — one code path, parity with the sibling, no
per-PR round trips. ``gh --json`` failing raises (``check=True``), so an absent
check is never masked as present.
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
    HEAL_KIND_CHECK_REARM,
    REARM_RECHECK_COOLDOWN_HOURS,
    plan_check_rearm,
)
from wgmesh_pipeline.selfheal.models import shift  # noqa: E402
from wgmesh_pipeline.selfheal.rearm import DEFAULT_REQUIRED_CONTEXT  # noqa: E402

REARM_SCRIPT = Path(__file__).resolve().parent / "rearm.sh"

# Injectable side effects -------------------------------------------------------
GhRun = Callable[[Sequence[str]], str]            # read-only gh, returns stdout
RearmFn = Callable[[str, int, str], str]          # (repo, number, branch) -> OUTCOME line
EnableAutoMergeFn = Callable[[str, int], None]    # (repo, number) -> enable auto-merge
GhMutate = Callable[[Sequence[str]], None]        # write gh (edit/comment)


def _real_gh_run(args: Sequence[str]) -> str:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    ).stdout


def _real_gh_mutate(args: Sequence[str]) -> None:
    subprocess.run(["gh", *args], check=True)


def _real_enable_automerge(repo: str, number: int) -> None:
    # gh-native equivalent of client.enable_auto_merge: arms GitHub auto-merge so
    # the PR merges once required checks pass. Idempotent (an already-enabled PR
    # is a benign no-op). Squash to match the box's merge method.
    subprocess.run(
        ["gh", "pr", "merge", str(number), "--repo", repo, "--auto", "--squash"],
        check=True,
    )


def _real_rearm(repo: str, number: int, branch: str) -> str:
    out = subprocess.run(
        ["bash", str(REARM_SCRIPT), repo, str(number), branch],
        check=True, capture_output=True, text=True,
    ).stdout
    return out.strip().splitlines()[-1] if out.strip() else ""


# Pure helpers ------------------------------------------------------------------

def normalize_mergeable(value: Any) -> str | None:
    """gh reports MERGEABLE / CONFLICTING / UNKNOWN; map UNKNOWN (and anything
    not yet computed) to None so the planner skips it this cycle."""
    return value if value in ("MERGEABLE", "CONFLICTING") else None


def present_contexts(rollup: Any) -> frozenset[str]:
    """Set of check/status context names present on a PR head, parsed from gh's
    ``statusCheckRollup``. A check-run carries ``name``; a commit status carries
    ``context`` — take whichever is present. An absent rollup is an empty set
    (no checks ran), which is exactly the re-arm signal."""
    names: set[str] = set()
    for item in rollup or []:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name") or item.get("context")
        if name:
            names.add(str(name))
    return frozenset(names)


def list_open_prs(target_repo: str, gh_run: GhRun) -> list[dict[str, Any]]:
    """Open PRs as planner-ready dicts: number, headRefName, title, isDraft,
    mergeable (tri), present_contexts (frozenset)."""
    raw = gh_run([
        "pr", "list", "--repo", target_repo, "--state", "open",
        "--limit", "200",
        "--json", "number,headRefName,mergeable,title,isDraft,statusCheckRollup",
    ])
    prs = json.loads(raw) if raw.strip() else []
    return [
        {
            "number": int(pr["number"]),
            "headRefName": pr.get("headRefName") or "",
            "title": pr.get("title") or "",
            "isDraft": bool(pr.get("isDraft")),
            "mergeable": normalize_mergeable(pr.get("mergeable")),
            "present_contexts": present_contexts(pr.get("statusCheckRollup")),
        }
        for pr in prs
    ]


def parse_outcome(line: str) -> str:
    """Extract OUTCOME=<slug> from a rearm.sh result line."""
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

def run_check_rearm(
    target_repo: str,
    state: Mapping[str, Any],
    now: str,
    *,
    dry_run: bool,
    gh_run: GhRun,
    enable_automerge_fn: EnableAutoMergeFn,
    rearm_fn: RearmFn,
    gh_mutate: GhMutate,
    required_context: str = DEFAULT_REQUIRED_CONTEXT,
    escalate_cooldown_hours: float = CONFLICT_ESCALATE_COOLDOWN_HOURS,
    recheck_cooldown_hours: float = REARM_RECHECK_COOLDOWN_HOURS,
) -> dict[str, Any]:
    """Plan + execute one check-rearm cycle, returning the new state dict.

    For each re-arm action: enable auto-merge FIRST (KTD2 — the backlog predates
    the box's auto-merge wiring), THEN push the empty commit. A re-arm sets a
    short recheck cooldown so the next tick doesn't re-push while the judge runs;
    repeated failures increment toward the cap and escalate. dry_run makes zero
    mutations and is surfaced by the caller to skip the state write.
    """
    prs = list_open_prs(target_repo, gh_run)
    tracker_in: Mapping[str, Any] = dict(state.get("retry_tracker") or {})
    plan = plan_check_rearm(
        prs, tracker_in, now,
        required_context=required_context,
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
                number, action.comment or "Merge-lane heal escalation.",
                gh_mutate=gh_mutate, target_repo=target_repo, dry_run=dry_run,
            )
            continue
        if action.kind != HEAL_KIND_CHECK_REARM:
            continue
        branch = branch_by_number.get(number, "")
        if dry_run:
            print(f"DRY_RUN re-arm PR #{number} ({branch}): would enable auto-merge + push empty commit")
            continue
        # KTD2: enable auto-merge BEFORE pushing the re-arm commit. A repo with
        # auto-merge disabled (OQ2) makes this raise — warn and still re-arm so
        # the check at least posts, rather than aborting the whole cycle.
        try:
            enable_automerge_fn(target_repo, number)
        except Exception as exc:  # noqa: BLE001 — resilience: never abort the cycle
            print(f"::warning::enable auto-merge failed for PR #{number}: {exc}")
        outcome = parse_outcome(rearm_fn(target_repo, number, branch))
        entry = dict(tracker.get(key) or {})
        if outcome == "rearmed":
            retries = int(entry.get("retries") or 0) + 1
            tracker[key] = {
                **entry, "retries": retries, "last_retry": now,
                "action": HEAL_KIND_CHECK_REARM,
                "cooldown_until": shift(now, hours=recheck_cooldown_hours),
            }
        elif outcome == "error":
            retries = int(entry.get("retries") or 0) + 1
            tracker[key] = {
                **entry, "retries": retries, "last_retry": now,
                "action": HEAL_KIND_CHECK_REARM,
                "cooldown_until": shift(now, hours=recheck_cooldown_hours),
            }
        else:  # skipped / non-bot / unknown — leave tracker untouched, log loudly
            print(f"::warning::re-arm PR #{number} returned OUTCOME={outcome}; no tracker change")

    # NB: deliberately no timestamp in the persisted state — the commit gate is a
    # byte diff, so an unchanged tracker must produce an identical file.
    return {**state, "retry_tracker": tracker}


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check-rearm orchestrator")
    parser.add_argument("--target-repo", default=os.environ.get("TARGET_REPO", ""))
    parser.add_argument("--state-file", default=os.environ.get(
        "CHECK_REARM_STATE", "company/check-rearm-state.json"))
    parser.add_argument("--now", default=os.environ.get("NOW", ""))
    parser.add_argument("--required-context", default=os.environ.get(
        "REQUIRED_CONTEXT", DEFAULT_REQUIRED_CONTEXT))
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

    new_state = run_check_rearm(
        args.target_repo, state, now,
        dry_run=args.dry_run,
        gh_run=_real_gh_run,
        enable_automerge_fn=_real_enable_automerge,
        rearm_fn=_real_rearm,
        gh_mutate=_real_gh_mutate,
        required_context=args.required_context,
    )

    if args.dry_run:
        print("DRY_RUN: no state written.")
    else:
        _write_state(state_path, new_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
