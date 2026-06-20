---
title: "feat: surgical requeue of failed issues (un-quarantine without wiping state)"
type: feat
date: 2026-06-20
depth: standard
origin: none (diagnosis from box journal; convergence stall layer 2)
---

# feat: surgical requeue of `failed` issues

**Target files:** `pipeline/wgmesh_pipeline/state/store.py`,
`pipeline/wgmesh_pipeline/main.py`, `.github/workflows/requeue-failed-issues.yml` (+ tests).
Deploys to the box via `update-pipeline-box`; the workflow itself runs one-shot over SSH.

## Summary

The convergence engine is stalled at the claim step: `reconcile seen=19 queued=0; claimed=none`
every tick. Root cause — the 17 growth issues hit `bump_attempt`'s `max_attempts=3` cap during
yesterday's implement-runner failure storm, so each was set to `stage="failed"`, which is **not
in `ACTIONABLE_STAGES`** (store.py:24). `claim_next` will never pick them up again. The
implement-runner fix (#1886) is deployed but can't be exercised because no issue ever reaches the
implement node.

The only built-in recovery is `RESET_QUEUE=1`, which **wipes the entire state DB** (all issues +
runs) and re-reconciles from scratch — blunt, risks duplicate spec PRs, loses `spec_pr`/`impl_pr`
linkage. This plan adds a **surgical** path: requeue specific (or all) `failed` issues back to an
actionable stage with `attempts` cleared, preserving their PR linkage, exposed via a one-shot
workflow that needs no full reprovision and no service restart.

## Problem Frame

- **Observed:** post-deploy box journal — `claimed=none` on every tick; 0 implement advances; the
  17 issues are `stage=failed`.
- **Mechanism:** `bump_attempt` (store.py:333) sets `stage="failed"` at `attempts >= 3`; `failed`
  ∉ `ACTIONABLE_STAGES`; `claim_next` skips it permanently.
- **Goal:** re-admit chosen `failed` issues to the funnel (at the stage matching their artifacts,
  default `spec_ready`) with `attempts=0`, without wiping state — so the fixed runner gets
  exercised and the backlog can drain.
- **Operator decision (2026-06-20):** "Build surgical reset" (not the `RESET_QUEUE` wipe).

---

## Scope Boundaries

**In scope**
- A targeted `requeue_failed` store method.
- A one-shot `--requeue-failed` CLI path in `main.py` that requeues then exits (never enters the
  poll loop).
- A `requeue-failed-issues.yml` dispatch workflow that runs the one-shot over SSH on the box.
- Tests for the store method and the CLI one-shot path.

**Out of scope**
- Layer 1 (implement runner) — fixed in #1886.
- Layer 3 (disabled GHA merge lane) — separate; even requeued+implemented PRs won't auto-merge
  until that's addressed. Flag it; don't solve it here.
- Raising `max_attempts` or auto-recovery of `failed` issues — a durable alternative, deferred.
- The `RESET_QUEUE` full-wipe path — left intact, untouched.

### Deferred to Follow-Up Work
- Auto-recovery: a periodic sweep that requeues `failed` issues whose `last_error` matches a
  now-fixed signature, so manual requeue isn't needed next time.
- Decide layer-3 PR-merge ownership (re-enable `Bot PR Review and Merge` / `Spec Auto-Approve`,
  or add a box merge action).

---

## Key Technical Decisions

- **KTD1 — Targeted UPDATE, not wipe.** `requeue_failed` flips `stage='failed'` rows to an
  actionable target stage and zeroes `attempts` (and clears `last_error`), preserving
  `spec_pr`/`impl_pr`/title. Preserves linkage the `RESET_QUEUE` wipe would destroy.
- **KTD2 — Default target stage `spec_ready`.** The quarantined issues failed the
  `spec_ready → implemented` advance and already have spec PRs; `spec_ready` re-enters them at the
  implement step. Make the target a parameter (default `spec_ready`) and validate it is in
  `ACTIONABLE_STAGES`.
- **KTD3 — Optional issue-number filter.** Requeue a given list of numbers, or all `failed` when
  none supplied. Lets the operator scope to the 17 (or a subset) and avoids touching unrelated
  failures.
- **KTD4 — One-shot CLI that exits.** `--requeue-failed` opens config + store, runs the requeue,
  prints a summary, and returns — it must NOT build the poller/forge or enter `run_forever`
  (unlike `--reset-queue`, which resets then polls). The long-running systemd service keeps
  running separately and claims the requeued issues on its next tick.
- **KTD5 — SSH one-shot workflow, no restart.** Mirror `diagnose-box-journal.yml` (hcloud resolve
  IP + deploy key) to run the one-shot against the box's shared state DB. No service restart,
  no reprovision. libsql/Turso tolerates the brief concurrent writer.

---

## High-Level Technical Design

```
operator dispatches requeue-failed-issues.yml (issues="730,731,…" | empty=all; target=spec_ready)
        │  SSH (deploy key) to box
        ▼
box: python -m wgmesh_pipeline.main --requeue-failed [--issues N,N] [--target-stage S]
        │  load_config → open_state_store
        ▼
store.requeue_failed(numbers, target_stage) :
        UPDATE issues SET stage=:target, attempts=0, last_error=NULL, updated_at=:now
        WHERE stage='failed' AND (:numbers empty OR number IN :numbers)
        │  prints "requeued=N numbers=[…]"; process EXITS (no poll loop)
        ▼
running systemd service (already on #1886 fix): next tick claim_next() now finds the
requeued spec_ready issues → implement node runs with bounded context → impl PR opens
```

Completion of the requeue is the UPDATE; convergence resumes on the service's own cadence.

---

## Implementation Units

### U1. `store.requeue_failed` — targeted un-quarantine

- **Goal:** Flip `failed` issues back to an actionable stage with cleared attempts, preserving
  linkage.
- **Requirements:** KTD1, KTD2, KTD3.
- **Dependencies:** none.
- **Files:**
  - `pipeline/wgmesh_pipeline/state/store.py`
  - `pipeline/tests/` (the store test module — match the existing one, e.g. `test_state_store.py`)
- **Approach:** Add `requeue_failed(self, numbers: Sequence[int] | None = None, *,
  target_stage: str = "spec_ready", now: datetime | None = None) -> dict[str, Any]`. Validate
  `target_stage in ACTIONABLE_STAGES` (raise `ValueError` otherwise). Build the UPDATE with
  `stage='failed'` plus an optional `number IN (…)` clause from `numbers`; set
  `stage=target_stage, attempts=0, last_error=NULL, updated_at=now`. Return
  `{"requeued": <rowcount>, "numbers": [<affected numbers>], "target_stage": target_stage}`.
  Mirror the parametrised-SQL + `_iso(_dt(now))` style already in the module.
- **Patterns to follow:** `reset_queue` (commit + return counts), `bump_attempt` (UPDATE shape,
  `now` handling), `claim_next` (cooldown/stage semantics) in the same file.
- **Test scenarios:**
  - One `failed` issue, no filter → its stage becomes `spec_ready`, `attempts=0`,
    `last_error` cleared; `spec_pr`/`impl_pr`/title preserved; return `requeued=1`.
  - Multiple `failed`, numbers filter to a subset → only listed issues change; others stay
    `failed`.
  - Non-`failed` issue in the numbers list → untouched (the `stage='failed'` guard).
  - `target_stage` not in `ACTIONABLE_STAGES` → raises `ValueError`, no writes.
  - Empty/no `failed` issues → `requeued=0`, no error.
  - After requeue, `claim_next` returns the requeued issue (it is now claimable).
- **Verification:** New tests green; a requeued issue is claimable immediately (no residual
  cooldown because `attempts=0` → `_cooldown(0)=0`).

### U2. `--requeue-failed` one-shot CLI path

- **Goal:** A box-runnable command that requeues then exits, never entering the poll loop.
- **Requirements:** KTD4.
- **Dependencies:** U1.
- **Files:**
  - `pipeline/wgmesh_pipeline/main.py`
  - `pipeline/tests/` (main/CLI test module)
- **Approach:** Add argparse flags: `--requeue-failed` (store_true), `--issues` (comma-separated
  numbers, optional), `--target-stage` (default `spec_ready`). In `main()`, when
  `--requeue-failed` is set, run a dedicated one-shot (`requeue_failed_main`): `load_config()` →
  `open_state_store(config)` → `store.requeue_failed(numbers, target_stage=…)` → print the summary
  → return. Do NOT construct the poller/forge/graph or call `asyncio.run(async_main(...))` on this
  path. Keep `--reset-queue` behaviour unchanged.
- **Patterns to follow:** existing `main()` argparse + the `reset_queue` print/summary style;
  `open_state_store(config)` usage from `async_main`.
- **Test scenarios:**
  - `main(["--requeue-failed"])` with a fake/in-memory store containing `failed` issues → calls
    `requeue_failed` with no number filter, prints the summary, does NOT start the poller
    (assert the poller / `async_main` loop is never invoked).
  - `main(["--requeue-failed", "--issues", "730,731"])` → parses `[730, 731]` and passes them
    through.
  - `main(["--requeue-failed", "--target-stage", "queued"])` → passes `queued` through.
  - Malformed `--issues` (e.g. `730,x`) → clear error, no partial run.
  - `--reset-queue` path still resets-then-polls (regression guard).
- **Verification:** The one-shot path returns without entering `run_forever`; existing
  `--reset-queue` tests still pass.

### U3. `requeue-failed-issues.yml` dispatch workflow

- **Goal:** Operator-triggerable, runs the one-shot on the box over SSH; no restart/reprovision.
- **Requirements:** KTD5.
- **Dependencies:** U2.
- **Files:**
  - `.github/workflows/requeue-failed-issues.yml`
- **Approach:** Copy the structure of `.github/workflows/diagnose-box-journal.yml`: inputs
  `server_name` (default `wgmesh-pipeline`), `issues` (CSV, default empty = all `failed`),
  `target_stage` (default `spec_ready`); `permissions: contents: read`; validate
  `DEPLOY_SSH_KEY` + `HCLOUD_TOKEN`; install hcloud; resolve box IP; SSH (with
  `UserKnownHostsFile=/dev/null`) and run the box venv python:
  `cd /opt/wgmesh-pipeline && <python> -m wgmesh_pipeline.main --requeue-failed
  [--issues "$ISSUES"] [--target-stage "$TARGET"]`, passing inputs as quoted env vars (scope-guard
  the `issues` value to `^[0-9,]*$` and `target_stage` to `^[a-z_]+$` before use). Echo the
  command output (the requeue summary).
- **Patterns to follow:** `diagnose-box-journal.yml` end-to-end (secret validation, hcloud,
  IP resolve, SSH key handling, cleanup); use the same box python entrypoint the service uses.
- **Test scenarios:** `Test expectation: none — declarative GHA workflow.` Validation is the
  post-merge dispatch (see end-to-end verification); statically confirm the input scope-guards and
  that the SSH command matches the U2 CLI surface.
- **Verification:** Dispatch with `issues` empty on a box that has `failed` issues → workflow logs
  `requeued=N`; the box's next tick logs `claimed=#<n>@spec_ready` and an advance.

---

## Risks & Dependencies

- **R1 — Concurrent DB access.** The one-shot writes while the systemd service reads/writes the
  same libsql/Turso DB. Mitigation: a single short UPDATE+commit; libsql serialises writers. If a
  transient lock appears, the workflow can be re-dispatched (idempotent: re-running requeues the
  same rows to the same stage, `requeued` may be 0 the second time).
- **R2 — Requeue to the wrong stage.** If an issue actually needs re-spec (no usable spec PR),
  `spec_ready` would send it to implement against a stale/missing spec. Mitigation: default fits
  the current 17 (they have spec PRs); `--target-stage queued` is available to force re-triage;
  `last_error` is cleared so the journal will show the fresh outcome.
- **R3 — Layer 3 still open.** Requeued issues that implement successfully produce impl PRs that
  **won't auto-merge** (GHA merge lane disabled). This plan exercises the runner fix and unblocks
  the funnel up to PR creation; merging is the separate deferred follow-up. State this when
  reporting results.
- **Dependency:** the implement-runner fix (#1886) must be live on the box first (it is) so the
  requeued issues don't immediately re-fail and re-quarantine.

## Verification (end-to-end)

1. Unit suites green: store + main CLI tests.
2. Merge → run `update-pipeline-box` (so the box has the new `--requeue-failed` entrypoint).
3. Dispatch `requeue-failed-issues.yml` (issues empty or the 17 numbers) → logs `requeued=N`.
4. `diagnose-box-journal` within ~1–2 ticks: `claimed=#<n>@spec_ready` → `advanced … -> implemented`
   with NO `reached max iterations`; a `fix: Issue #N` impl PR opens; implement tokens bounded.
5. Note remaining layer-3 gap: the new impl PRs need a merge path before `aged_open_items` falls.
