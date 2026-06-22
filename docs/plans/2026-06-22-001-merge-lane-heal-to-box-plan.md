# Plan — Merge-lane-heal → box control loop (retire conflict-heal.yml)

2026-06-22. Operator principle (project_actions_cicd_only_retarget):
> *"the only thing that must be left in github actions is [a CI/CD pipeline]... autobox is just another developer"*

`conflict-heal.yml` (3 passes: conflict-rebase + check-rearm + stale-base-rebase) is a
scheduled **Actions cron doing pipeline orchestration** — not CI/CD. Move it onto the box
control loop and retire the cron. Operator decisions (2026-06-22): **scope = merge-lane-heal
only** (pipeline-health.yml stays for a separate cut); **box heals BOTH repos** (seed + meta).

## Current state (recon)

- Box loop = `main.py async_main` → `Poller.run_forever` (claims/advances issues) + optional
  `ControlLoopScheduler` (4 shadow-gated modules: supervisor / selfheal / observation /
  strategy_audit). `run_self_heal` is already a control-loop module (stale-stage sweeps).
- Merge-lane-heal is NOT a box module — it lives only in `conflict-heal.yml` (Actions cron,
  active) via `company/scripts/{conflict-heal,check-rearm,stale-base-heal}/run.py` (gh CLI).
- The 3 PLANNERS (`selfheal/{conflict,rearm,stale_base}.py`) are pure + box-ready.
- `GitHubClient` is single-repo (bound to `config.target_repo`), REST via `requests`.

## Design

A 5th control-loop module `merge_lane`, mirroring the existing four: gather → plan → (shadow:
return; live: execute) → persist. Gated by `MERGE_LANE_HEAL_LIVE` (default false). Reuses the
3 pure planners. Executes via the **forge client** (REST list/label/comment/auto-merge) +
`conflict-heal/rebase.sh` (git rebase; the box has git + `WGMESH_BOT_PAT`). Cross-repo: the
module runs once per forge in `[seed_forge, meta_forge]`; `meta_forge` = `GitHubClient` on a
config copy with `target_repo = <meta slug>`.

## Units (U1–U3 land INERT behind the flag; U4 is the operator-gated cutover)

- **U1 — forge accessors (additive, zero-risk).** Add to `forge/protocol.py` + `github/client.py`:
  `compare_behind_by(head_branch) -> int` (GET `/compare/main...{head}` → `behind_by`, 404→0)
  and `pr_has_failing_check(number) -> bool` (GET PR check-runs/statuses, any FAILURE). The
  stale-base planner needs both; conflict/rearm don't. Quackback/Gitea get no-op/raise stubs as
  the protocol requires. Tests: `test_github_client_merge_lane_accessors.py`.

- **U2 — box-native module `selfheal/merge_lane.py`.** `run_merge_lane_heal(forge, state, now,
  *, live, rebase_fn, repo_label) -> MergeLaneHealRun` (shape mirrors `SelfHealRun`): list open
  PRs via forge; resolve mergeable/behindBy/failing; run `plan_conflict_heal` → `plan_check_rearm`
  → `plan_stale_base_heal` (same A→B→C order as the cron); in shadow return planned actions +
  state, in live execute (forge label/comment/auto-merge + `rebase_fn` for rebase/empty-commit).
  Injectable side effects (NoCallForge-testable). Tests: `test_merge_lane_heal.py` (shadow plans
  nothing-executed; live drives fakes; per-pass selection; cross-pass ordering).

- **U3 — wire as the 5th ControlLoopScheduler module + cross-repo.** Add `MERGE_LANE_HEAL_LIVE`
  + `merge_lane_heal_interval_seconds` to config; register the module in `control_loop/__init__.py`
  with its own gate + state row; build `[seed_forge, meta_forge]` and run the module per repo.
  Lands shadow (LIVE=false) — runs each cycle, executes nothing.

- **U4 — cutover (operator-gated, after shadow-proven).** `set-box-env MERGE_LANE_HEAL_LIVE=true`
  (+ `CONTROL_LOOP_ENABLED=true` if not already) → `gh workflow disable "Conflict Heal"`. Verify
  one live box cycle rebases a stale-base PR + zero cron runs. Rollback = re-enable cron + flag
  false.

## Safety

- U1–U3 inert: `MERGE_LANE_HEAL_LIVE` default false → the module runs in shadow (plans, executes
  nothing) the moment it's wired; no force-push from the box until U4.
- Double-heal guard: U4 disables the cron in the SAME change that flips the flag (only one
  executor live at a time).
- Reuses `rebase.sh` (bot-branch guard + `--force-with-lease` + empty-after-rebase) — no new
  force-push logic.

## Out of scope

pipeline-health.yml (stale-stage heal) — separate cut. Durable post-merge/merge-queue gate.
