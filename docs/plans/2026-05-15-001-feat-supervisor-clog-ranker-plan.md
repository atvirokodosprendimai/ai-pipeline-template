---
title: "feat: Supervisor clog ranker + pipeline-health mutation assertion"
type: feat
status: active
date: 2026-05-15
origin: docs/brainstorms/2026-05-15-supervisor-clog-ranker-requirements.md
---

# feat: Supervisor clog ranker + pipeline-health mutation assertion

## Summary

Stand up `supervisor-rank.yml` workflow that snapshots open PRs+issues across `ai-pipeline-template` and `wgmesh`, classifies each into a pipeline stage, ranks the top 3–5 clogs by `dwell × downstream_blocked`, and posts a recommended action per clog into a single idempotent `supervisor-rank` tracking issue. Backfill `pipeline-health.yml` with a state-mutation assertion that opens a `supervisor-dead` issue when `company/pipeline-health-state.json` fails to advance across runs. Read-only v1 — no auto-actions. Stage taxonomy lives in `company/pipeline-stages.json`. Reuses the App-token + JSON-state + cron patterns already in `pipeline-health.yml` and `strategy-audit.yml`.

---

## Problem Frame

`ai-pipeline-template` is the supervisor over the seeded-product pipeline. It monitors but does not rank, decide, or escalate (see origin §Problem). Pulse 2026-05-15 confirmed five distinct supervisor failure modes simultaneously — frozen state file with green cron, 9-day-old spec PRs, 7-day-old triage stalls, un-actioned audit-drift PRs, and a 40-day Goose-pipeline silence — none of which the existing supervisor surfaced to the operator as a ranked priority.

---

## Requirements

- R1. On each run, snapshot open PRs+issues across `atvirokodosprendimai/{ai-pipeline-template, wgmesh}` (see origin: §Scope > In).
- R2. Classify each item into a pipeline stage per the canonical taxonomy: `triage | spec | build | review | merge | verify | revenue | unknown` (see origin: §Key Decisions §6).
- R3. Compute `dwell_hours` and `downstream_blocked_count` per item; rank top 3–5 by `dwell × downstream_blocked` (see origin: §Key Decisions §7).
- R4. Per ranked clog, emit a recommended action from the fixed set: `retry-copilot | bounce-label | auto-close-superseded | post-rah-bounty | escalate-needs-human | manual-merge` (see origin: §Scope > In).
- R5. Maintain a single idempotent `supervisor-rank` GitHub issue; rewrite body on every run; comment only when rank order changes (see origin: §Key Decisions §5).
- R6. Backfill `pipeline-health.yml`: assert state-file mutation per run; if `company/pipeline-health-state.json` `last_check` does not advance 2 consecutive runs, open `supervisor-dead` `needs-human` issue (see origin: §Key Decisions §2).
- R7. Read-only v1 — workflow does not auto-execute any recommended action (see origin: §Scope > In, §Key Decisions §4).
- R8. Workflow self-asserts: if its own state output is empty/malformed, exit non-zero — `success` must mean rank was emitted (see origin: §Risks > "Same anti-pattern as today").

---

## Scope Boundaries

- No auto-execution of recommended actions; humans (or a follow-up workflow) act on the ranked output.
- No deadline-scheduler / event-driven gate refactor (Approach C from origin); deferred until 3rd seed product.
- No cross-org rollout to `CloudLLM-ai/*` or `nycterent/*`.
- No new dashboard UI; the GitHub issue body is the only surface for v1.
- No replacement of GitHub Actions as the orchestrator.
- No modification of Copilot/Goose agents themselves.

### Deferred to Follow-Up Work

- Auto-execution wiring for the safest recommended actions (e.g., `auto-close-superseded` for audit-drift PRs > 24h): separate PR after 2–3 runs validate the ranks.
- Chimney dashboard structured-data integration (origin §Open Questions): separate PR.
- Token-strategy consolidation across remaining 8 `PUSH_TOKEN`-using workflows: tracked in [pipeline-health App migration memory](../../.claude/projects/-Users-oldroot-Repos-ai-pipeline-template/memory/project_pipeline_health_app_migration.md), not this plan.

---

## Context & Research

### Relevant Code and Patterns

- `.github/workflows/pipeline-health.yml` — App-token auth, state-file commit pattern, jq-based JSON mutation (`jq … > /tmp/state.json && mv /tmp/state.json $STATE_FILE`), `*/30 * * * *` cadence, `concurrency: group:` lock. Mirror exactly.
- `.github/workflows/strategy-audit.yml` — `actions/create-github-app-token@v2` with `vars.APP_ID` + `secrets.APP_PRIVATE_KEY`, `workflow_dispatch` with optional input, `skip-guard` step pattern. Mirror exactly.
- `.github/workflows/bot-pr-review-merge.yml` — App-token + `GH_TOKEN` env-var pattern for `gh` CLI; same token path applies here.
- `company/pipeline-health-state.json` — existing schema (`last_check`, `checks_run`, `issues_healed_total`, `retry_tracker`, `funnel_signals`, `idle_signal`, `last_run_summary`). Plan adds a `last_mutation_attempted_at` + `consecutive_no_mutation_runs` pair without breaking schema.
- `company/strategy-audit-baseline.json` and `company/loop-state.json` — companion-state-file precedent; new `company/supervisor-rank-state.json` follows the same shape conventions.

### Institutional Learnings

- [Supervisor must self-rank, don't ask operator](../../.claude/projects/-Users-oldroot-Repos-ai-pipeline-template/memory/feedback_supervisor_must_self_rank.md) — keep ranker output ranked + actionable; never frame as "operator picks from list".
- [Cron `success` ≠ state mutation](../../.claude/projects/-Users-oldroot-Repos-ai-pipeline-template/memory/feedback_cron_success_not_equal_state_mutation.md) — directly informs U5 mutation-assertion design.
- [bot-pr-review-merge synchronize gap](../../.claude/projects/-Users-oldroot-Repos-ai-pipeline-template/memory/feedback_bot_merge_trigger_gap_synchronize.md) — the `merge` stage detector must treat "approved + clean but synchronize-event not triggered" as a clog signal.
- [Required check + path filter = merge deadlock](../../.claude/projects/-Users-oldroot-Repos-ai-pipeline-template/memory/feedback_required_check_path_filter_blocks_merge.md) — `supervisor-rank.yml` must use an always-run trigger, no `paths:` filter, or it will not satisfy any branch-protection required check.
- [Workflow self-bootstrap hashFiles guard](../../.claude/projects/-Users-oldroot-Repos-ai-pipeline-template/memory/feedback_workflow_self_bootstrap_hashfiles_guard.md) — if the workflow invokes a script newly added in the same PR, gate that step with `hashFiles('path') != ''` to survive the on-main-pre-merge CI run.
- [Non-fatal bash helper contract](../../.claude/projects/-Users-oldroot-Repos-ai-pipeline-template/memory/feedback_non_fatal_bash_helper_contract.md) — for any step labeled "non-fatal", use trap-on-EXIT rather than `set -euo pipefail`; gate executable check on `[ -f ]` not `[ -x ]`.
- [GH Actions secret gotchas](../../.claude/projects/-Users-oldroot-Repos-ai-pipeline-template/memory/feedback_github_actions_secret_gotchas.md) — default `GITHUB_TOKEN` is read-only when `permissions: contents: read`. Workflow needs `issues: write` + `pull-requests: read` + `contents: write` for state commit.

---

## Key Technical Decisions

- **Workflow split.** Net-new `.github/workflows/supervisor-rank.yml` is separate from `pipeline-health.yml`. Rationale: health is the per-target-repo doctor; rank is cross-repo + cross-stage triage. Keeps each workflow's concurrency surface narrow.
- **Bash + jq, no new runtime.** Implementation stays in shell, mirroring existing pipeline-health.yml style. Rationale: no Python/Node added to CI, smallest reviewable diff, matches operator's mental model for the rest of the supervisor.
- **Stage taxonomy as committed JSON.** `company/pipeline-stages.json` is the single source of truth for stage names + classification heuristics. Rationale: greppable, diffable, reusable later by deadline-scheduler refactor (Approach C in origin).
- **Idempotent single issue via stable title.** Workflow searches for an open issue titled exactly `supervisor-rank: top pipeline clogs`; if none, creates one; else edits body. Rationale: avoids audit-drift-PR anti-pattern of pile-up. Comments only on rank change.
- **Cadence: every 4h.** Matches pulse rhythm; 1h would be tighter but the recommended-action set is human-paced anyway. Workflow_dispatch on demand.
- **App token, not PUSH_TOKEN PAT.** Per origin §Open Questions and memory `project_pipeline_health_app_migration` — pupabobas App token via `vars.APP_ID` + `secrets.APP_PRIVATE_KEY`, both org-inherited. Rationale: avoids `nycterent`-as-author email-spam loop already paid down in earlier work.
- **State storage: JSON in repo.** `company/supervisor-rank-state.json` committed by workflow (App-token author). Rationale: greppable, time-travelable via git, matches existing `pipeline-health-state.json` precedent. GH-artifact alternative considered and rejected — artifacts expire and aren't diffable.
- **Loud-fail for pipeline-health is in-process, not a second workflow.** A new final step in `pipeline-health.yml` asserts the state file's `last_check` advanced; if not, the step fails the job AND increments `consecutive_no_mutation_runs`; at >=2, the step opens `supervisor-dead` issue. Rationale: keeps the assertion adjacent to the steps it audits — separating into a sibling workflow recreates the same trust-the-conclusion problem.

---

## Open Questions

### Resolved During Planning

- Token strategy: **App token** (matches pipeline-health.yml + strategy-audit.yml; sidesteps email-spam loop).
- State storage: **JSON in repo** at `company/supervisor-rank-state.json`.
- Cadence: **every 4h** (`0 */4 * * *`) plus `workflow_dispatch`.
- Chimney dashboard: **deferred to follow-up** — v1 emits to GH issue only.

### Deferred to Implementation

- Exact dwell-threshold-per-stage values (e.g., spec-PR > 48h trigger). Implementation will tune from observed data over the first 2–3 runs; initial values land as constants in `pipeline-stages.json`.
- Stage-classification edge cases (PRs with mixed labels, issues with `needs-human` AND `copilot-triaging`). Implementation will discover via `stage: unknown` emit, then encode rules.
- `downstream_blocked_count` heuristic — initial implementation = "count of `approved-for-build` issues whose spec PR is the clogged item". May need refinement post-first-run.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
cron(*/4h)
   │
   ▼
┌──────────────────────────────────────────────┐
│ supervisor-rank.yml                          │
│                                              │
│ 1. snapshot.sh    → /tmp/snapshot.json       │
│    (gh pr/issue list for both target repos)  │
│                                              │
│ 2. classify.sh    → /tmp/classified.json     │
│    (reads pipeline-stages.json + snapshot)   │
│                                              │
│ 3. rank.sh        → /tmp/ranked.json         │
│    (dwell × downstream_blocked, top-N)       │
│                                              │
│ 4. recommend.sh   → /tmp/ranked.json (enriched)│
│    (per stage → action from fixed set)       │
│                                              │
│ 5. publish.sh                                │
│    ├── find/create "supervisor-rank" issue  │
│    ├── edit body with ranked list           │
│    ├── compare with prior state             │
│    │   └── if rank changed → post comment   │
│    └── write company/supervisor-rank-state  │
│                                              │
│ 6. assert.sh                                 │
│    └── if no state mutation → exit 1        │
└──────────────────────────────────────────────┘

pipeline-health.yml (existing)
   │
   ├── (existing heal steps)
   ▼
┌──────────────────────────────────────────────┐
│ NEW final step: assert state mutation        │
│                                              │
│ - read company/pipeline-health-state.json    │
│ - compare last_check to start-of-run timestamp│
│ - if unchanged:                              │
│     consecutive_no_mutation_runs++           │
│     if >= 2 → open supervisor-dead issue     │
│     exit 1                                   │
│ - if advanced:                               │
│     consecutive_no_mutation_runs = 0         │
└──────────────────────────────────────────────┘
```

Ranked-issue body shape:

```
# supervisor-rank: top pipeline clogs

Updated: 2026-05-15T22:00Z  (run #N)

## Top 3 clogs

1. **spec-stage frozen** — 8 PRs unmerged, oldest 9d (#741)
   - Stage: spec
   - Dwell × blocked: 216h × 8 = 1728
   - Recommended action: `manual-merge` — operator approve batch or escalate-needs-human
   - Items: #741, #743, #744, #747, #749, #750, #753

2. **copilot-triaging stuck (wgmesh)** — 5 issues, oldest 17d (#510)
   - Stage: triage
   - Dwell × blocked: 408h × 5 = 2040
   - Recommended action: `bounce-label` — strip copilot-triaging, retry-copilot
   - Items: wgmesh#510, wgmesh#539, wgmesh#540, wgmesh#573, wgmesh#584

3. ...

## Stage summary
- triage: 5 | spec: 8 | build: 0 | review: 5 | merge: 0 | verify: 4 | revenue: 1 | unknown: 0

## State
- Prior run: 2026-05-15T18:00Z (no rank change)
- File: company/supervisor-rank-state.json
```

---

## Implementation Units

### U1. Stage taxonomy + classification heuristics

**Goal:** Establish `company/pipeline-stages.json` as canonical stage definitions and classification rules; document the seven-stage taxonomy.

**Requirements:** R2.

**Dependencies:** None.

**Files:**
- Create: `company/pipeline-stages.json`
- Test: `.github/scripts/test-classify.sh`

**Approach:**
- JSON document with three top-level keys: `stages` (array of stage names in pipeline order), `classification_rules` (per-stage: label patterns, title prefixes, label-absence rules), `dwell_thresholds_hours` (per-stage escalation threshold), `recommended_actions` (per-stage default action).
- Stages: `triage | spec | build | review | merge | verify | revenue`. `unknown` reserved for non-matching items.
- Each rule is jq-compatible (string-equality on label name, string-prefix on title).
- Initial dwell thresholds: triage 72h, spec 48h, build 24h, review 48h, merge 24h, verify 96h, revenue 168h. Mark in JSON as "initial; tune from data".

**Test scenarios:**
- Happy path: a `gh issue` JSON object with `labels: [{name: "copilot-triaging"}]` classifies to `triage`.
- Happy path: a `gh pr` JSON object with `title: "spec: Issue #N — ..."` classifies to `spec`.
- Happy path: a `gh pr` JSON object with `labels: [{name: "approved-for-build"}]` and no impl-PR child classifies to `build`.
- Edge case: an item with BOTH `needs-human` and `copilot-triaging` labels — `needs-human` wins (higher escalation precedence).
- Edge case: an issue with no labels and no title-prefix match classifies to `unknown`.
- Error path: malformed `pipeline-stages.json` causes `classify.sh` to exit non-zero with message naming the bad rule.

**Verification:** `jq` validates JSON; running the classifier against a fixture of known issues produces the expected stage breakdown.

---

### U2. Snapshot + classifier scripts

**Goal:** Extract bash logic from inline YAML into `.github/scripts/` to make it shell-testable and reviewable.

**Requirements:** R1, R2.

**Dependencies:** U1.

**Files:**
- Create: `.github/scripts/snapshot-clogs.sh`
- Create: `.github/scripts/classify-clogs.sh`
- Create: `.github/scripts/test-classify.sh`
- Modify: none

**Approach:**
- `snapshot-clogs.sh`: takes `TARGET_REPOS` env var (comma-separated); for each repo, calls `gh pr list ... --json number,title,labels,createdAt,updatedAt,isDraft` and `gh issue list ... --json ...`; outputs a unified JSON array to stdout.
- `classify-clogs.sh`: reads snapshot from stdin or `$1`; reads `company/pipeline-stages.json`; emits same JSON with added `stage` and `dwell_hours` fields per item.
- Both scripts: `set -euo pipefail` at top; functions only; no global side-effects; stdout is JSON, stderr is logs.

**Execution note:** Write `test-classify.sh` first with a fixture of 6–8 known-classified items before implementing `classify-clogs.sh`.

**Patterns to follow:**
- Existing inline-bash style in `pipeline-health.yml` (jq with `--argjson`/`--arg` for typed inputs).
- `validate-spec.sh` for shell-script entry-point conventions.

**Test scenarios:**
- Happy path: classify a snapshot of today's actual repo state; output stage histogram matches manual inspection.
- Happy path: classify an empty snapshot → empty array, exit 0.
- Edge case: classify an item where `updatedAt > createdAt` — dwell = now − updatedAt (treat label change as dwell reset for `copilot-triaging` stage, dwell = now − createdAt elsewhere).
- Error path: missing `company/pipeline-stages.json` → script exits non-zero with named error.
- Error path: malformed JSON on stdin → exit non-zero.
- Integration: `snapshot-clogs.sh | classify-clogs.sh` chains without error.

**Verification:** `bash .github/scripts/test-classify.sh` passes against the committed fixture; the script can be invoked locally with a `gh auth login` session and produces a useful classified output.

---

### U3. Rank + recommend scripts

**Goal:** Take a classified snapshot and produce a ranked top-N list with per-clog recommended actions.

**Requirements:** R3, R4.

**Dependencies:** U2.

**Files:**
- Create: `.github/scripts/rank-clogs.sh`
- Create: `.github/scripts/recommend-actions.sh`
- Create: `.github/scripts/test-rank.sh`

**Approach:**
- `rank-clogs.sh`: reads classified JSON; for each stage, computes `dwell × downstream_blocked`. `downstream_blocked` heuristic v1:
  - For `spec` stage: count of open `approved-for-build` issues in same repo where the impl PR has not yet been opened.
  - For `triage` stage: count of items in `spec | build | review` stages dependent on the same repo (proxy: open items in same repo with later pipeline stages — simplified, refine post-launch).
  - For `merge` stage: count of approved-but-unmerged PRs in same repo (self-count).
  - For other stages: 1 (no blast-radius signal in v1).
- Outputs top-N (N=5) sorted by score descending.
- `recommend-actions.sh`: reads ranked JSON; reads `pipeline-stages.json` for `recommended_actions` map; emits ranked JSON with `recommended_action` field added per clog. Allowed actions enforced via jq enum check.

**Patterns to follow:**
- `strategy-audit.yml` baseline-diff pattern for "compare current with prior" logic.

**Test scenarios:**
- Happy path: 3 spec PRs with dwell 24h, 48h, 96h and 5 downstream blocked each → ranked highest-first by score.
- Happy path: a `revenue` clog with dwell 168h and blocked=1 ranks lower than a `spec` clog with dwell 48h and blocked=8.
- Edge case: empty classified snapshot → ranked output is `{"top": [], "stage_summary": {…}}`, exit 0.
- Edge case: tie in score — break by `created_at` ascending (older first).
- Error path: `recommend-actions.sh` receives a stage not in `recommended_actions` map → emits `recommended_action: null` with warning to stderr, does not exit non-zero (graceful fallback).
- Integration: `classify | rank | recommend` chains end-to-end on the today-fixture and produces a top-5 list that matches the manual ranking from the session pulse.

**Verification:** `bash .github/scripts/test-rank.sh` passes; end-to-end pipeline run on a checked-in fixture produces the expected ranked-and-recommended JSON.

---

### U4. Publish to idempotent `supervisor-rank` issue

**Goal:** Find or create the single `supervisor-rank` tracking issue and update its body; comment only on rank change.

**Requirements:** R5.

**Dependencies:** U3.

**Files:**
- Create: `.github/scripts/publish-rank.sh`
- Create: `.github/scripts/test-publish.sh`

**Approach:**
- `publish-rank.sh`: takes ranked JSON + prior-state path as inputs.
- Searches: `gh issue list --repo $GH_REPO --search 'supervisor-rank: top pipeline clogs in:title is:open' --json number,title`.
- If 0 matches → `gh issue create` with stable title, label `supervisor`, body from template.
- If 1 match → `gh issue edit $N --body-file /tmp/body.md`.
- If >1 → fail loud; the workflow tried to create twice or someone duplicated manually.
- Compares the new top-3 (by item number ordering) with the prior state's top-3; if different, posts a one-line comment naming what entered/exited.
- Writes `company/supervisor-rank-state.json` with `{ "last_run_at", "last_run_top_ids", "rank_changed", "run_number" }`.

**Patterns to follow:**
- `pipeline-health.yml` jq-then-mv state mutation pattern.
- App-token + `GH_TOKEN` env exactly like `bot-pr-review-merge.yml`.

**Test scenarios:**
- Happy path: first-ever run → issue created, state JSON written, no comment posted (no prior state).
- Happy path: second run, same top-3 → body edited, no comment.
- Happy path: second run, top-3 changed → body edited AND single comment posted.
- Edge case: GH API rate-limited mid-run → script retries with exponential backoff up to 3 attempts, then exits non-zero with named error.
- Edge case: two existing `supervisor-rank` issues open (duplicate) → script exits non-zero, does not touch either, surfaces both numbers to the operator.
- Error path: missing `GH_TOKEN` → exit non-zero with named error.
- Integration: run end-to-end against a fork of the repo, verify the issue body matches the expected template.

**Verification:** Manual dispatch run against the actual repo produces one `supervisor-rank` issue with a ranked top-N list; subsequent dispatch updates the same issue without creating duplicates.

---

### U5. Mutation assertion + supervisor-dead in `pipeline-health.yml`

**Goal:** Make `pipeline-health.yml` loud-fail when it cannot prove it advanced state, and open a `supervisor-dead` `needs-human` issue after 2 consecutive failures.

**Requirements:** R6, R8.

**Dependencies:** None (independent of U1–U4 — can land in parallel, but plan-order keeps it as U5 because U4 establishes the issue-creation convention).

**Files:**
- Modify: `.github/workflows/pipeline-health.yml`
- Modify: `company/pipeline-health-state.json` (schema extension)
- Create: `.github/scripts/assert-state-mutation.sh`

**Approach:**
- At start of `heal` job, capture `pre_run_last_check` from the state file.
- New final step `Assert state mutation`:
  - Reads `last_check` from state file post-run.
  - If `last_check == pre_run_last_check` (no advance):
    - Increment `consecutive_no_mutation_runs` (init 0 if absent).
    - If `consecutive_no_mutation_runs >= 2`: open or comment-update `supervisor-dead: pipeline-health frozen` issue, label `needs-human`.
    - Exit 1 (workflow conclusion = failure).
  - Else: reset `consecutive_no_mutation_runs = 0`.
  - Commit state file via App-token using the existing commit-state-via-PR pattern OR direct push (mirror what `pipeline-health.yml` already does).
- Extends `pipeline-health-state.json` schema with `consecutive_no_mutation_runs: int`. Backward-compatible (absent → treated as 0).

**Execution note:** Test-first — write `assert-state-mutation.sh` with a fixture of "pre=2026-05-10, post=2026-05-10" → must fail; "pre=2026-05-10, post=2026-05-15" → must pass.

**Patterns to follow:**
- Existing `pipeline-health.yml` jq-state-mutate pattern.
- `bot-pr-review-merge.yml` issue-create-or-update pattern.

**Test scenarios:**
- Happy path: state file `last_check` advances during the run → assertion passes, `consecutive_no_mutation_runs` reset to 0.
- Failure path: state file unchanged, prior `consecutive_no_mutation_runs=0` → increment to 1, exit 1, no `supervisor-dead` issue yet.
- Failure path: state file unchanged, prior `consecutive_no_mutation_runs=1` → increment to 2, open `supervisor-dead` issue, exit 1.
- Failure path: state file unchanged, prior `consecutive_no_mutation_runs=2`, supervisor-dead issue already open → comment "still frozen" on existing issue, exit 1, do not open second issue.
- Edge case: state file missing entirely → treat as "no mutation", same path as above.
- Edge case: state file present but malformed JSON → exit 1, open `supervisor-dead` immediately (this is a worse failure mode than no-advance).
- Integration: dispatch the workflow manually with the current frozen state file in place; verify it fails and surfaces the right error.

**Verification:** A dispatched run against the current frozen state-file should fail the workflow and open `supervisor-dead` after the 2nd dispatch.

---

### U6. New `supervisor-rank.yml` workflow

**Goal:** Wire U2–U4 into a cron + workflow_dispatch GH Actions workflow.

**Requirements:** R1, R5, R7, R8.

**Dependencies:** U2, U3, U4.

**Files:**
- Create: `.github/workflows/supervisor-rank.yml`

**Approach:**
- Triggers: `cron: '0 */4 * * *'` (every 4h) + `workflow_dispatch` (no inputs in v1).
- `permissions:` `contents: write` (state commit), `issues: write` (publish), `pull-requests: read` (snapshot), `actions: read`.
- `concurrency: { group: supervisor-rank, cancel-in-progress: false }`.
- Single job `rank`; steps:
  1. Generate App token (mirror `pipeline-health.yml`).
  2. Checkout repo with App token, `fetch-depth: 0`.
  3. `hashFiles('.github/scripts/snapshot-clogs.sh') != ''` guard (per memory `feedback_workflow_self_bootstrap_hashfiles_guard`).
  4. `Snapshot` step → `/tmp/snapshot.json`.
  5. `Classify` step → `/tmp/classified.json`.
  6. `Rank` step → `/tmp/ranked.json`.
  7. `Recommend` step → `/tmp/ranked.json` (enriched).
  8. `Publish` step → updates `supervisor-rank` issue, writes `company/supervisor-rank-state.json`.
  9. `Commit state` step (mirror `strategy-audit.yml` commit pattern).
  10. `Assert ranked output non-empty` final step → exit 1 if `/tmp/ranked.json` is empty or malformed.

**Patterns to follow:**
- `strategy-audit.yml` — same trigger shape, same permissions block, same App-token + commit-state choreography.
- `pipeline-health.yml` — same concurrency lock pattern.

**Test scenarios:**
- Happy path: workflow_dispatch fires; produces a `supervisor-rank` issue with ranked top-N; commits new state JSON.
- Happy path: second dispatch — body edited, no duplicate issue.
- Edge case: `snapshot-clogs.sh` returns empty (no open items anywhere) → publish step writes an "all clear" body, no error.
- Error path: classify script absent (script-bootstrap order bug) → `hashFiles` guard skips dependent steps, workflow exits with explicit "scripts not yet on main" notice (not failure).
- Error path: GH API auth fails → snapshot step exits non-zero, no state file mutated, workflow conclusion = failure.
- Integration: end-to-end dispatch produces the issue and commits the state file in a single run.

**Verification:** Workflow file passes `actionlint`; one manual dispatch produces a ranked issue.

---

### U7. Pulse + chimney integration hook (read-only)

**Goal:** Make the ranked output discoverable by the next `/pulse` run and (optionally) by chimney dashboard.

**Requirements:** Supports STRATEGY.md `self_heal_resolution_rate` metric; origin §Open Questions.

**Dependencies:** U4.

**Files:**
- Modify: `.compound-engineering/config.local.yaml` (add `supervisor_rank_state` pointer in pulse_metric_sources)
- Modify: `docs/pulse-reports/*.md` template — no code change; this unit only records the convention.

**Approach:**
- Add `self_heal_resolution_rate=company/supervisor-rank-state.json` entry to `pulse_metric_sources` so pulse runs read it.
- No active code change in pulse machinery — the operator runs `/pulse` and the read happens via the standard config-pointer resolution.

**Test scenarios:**
- Test expectation: none — pure config pointer addition with no logic change.

**Verification:** Next `/pulse` run mentions `supervisor-rank` issue number in the Followups section if it has open clogs.

---

## System-Wide Impact

- **Interaction graph:** New workflow adds an `issues: write` writer; existing workflows that comment on `supervisor-rank: …` titled issues are unaffected (none currently do).
- **Error propagation:** `supervisor-rank.yml` failures are isolated — no other workflow depends on its state file. `pipeline-health.yml`'s new mutation assertion can surface `supervisor-dead` issue, which feeds the `needs-human` labeling convention already used.
- **State lifecycle risks:** Concurrent dispatches blocked by `concurrency: group: supervisor-rank, cancel-in-progress: false` — same pattern as `pipeline-health`.
- **API surface parity:** No external API surface added; only internal GH issue + JSON file.
- **Integration coverage:** End-to-end dispatch + 2nd dispatch on same state = best integration test (scripted in U6 verification).
- **Unchanged invariants:**
  - `pipeline-health.yml`'s existing 17 heal steps remain untouched; the new assertion is purely additive at end-of-job.
  - Existing `company/pipeline-health-state.json` schema is extended, not changed — old fields preserved, `consecutive_no_mutation_runs` is additive.
  - Polar / Stripe / Goose / Copilot pipelines untouched.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Mis-classification puts wrong items in `unknown` stage and ranks them as 0 | Emit `unknown`-stage items in a separate "needs taxonomy" section of the issue body; operator labels manually for 1 week, feeds into `pipeline-stages.json` updates. |
| `downstream_blocked_count` heuristic produces noisy ranks | v1 heuristic is intentionally simple; refine after 2–3 runs of operator inspection. Top-N=5 keeps it small enough to scan even with some noise. |
| Operator ignores `supervisor-rank` issue (same anti-pattern as audit-drift PRs) | Single issue (not PR), comments only on rank change, kill criterion explicit in origin §Success Criteria — if ignored 7 days, the ranker is deleted. |
| `pipeline-health.yml` mutation-assertion creates a noisy `supervisor-dead` issue if a one-off legitimate no-op happens | 2-consecutive-runs gate prevents single-flap noise. `consecutive_no_mutation_runs` reset on first successful mutation. |
| Self-bootstrap CI hang — workflow added in same PR as scripts can't find them on main yet | `hashFiles` guard pattern per memory; final assertion is gated on script presence. |
| App token expiry breaks the cron silently | Mutation assertion catches this — if the workflow can't authenticate, the publish step fails, state isn't written, next run sees no advance, supervisor-dead fires. |

---

## Documentation / Operational Notes

- After first successful dispatch, add a short paragraph to `STRATEGY.md` under `Tracks > Self-heal & resilience` pointing at the `supervisor-rank` issue as the leading-metric surface.
- No runbook update needed for v1 — the issue body is self-describing.
- Memory update after merge: revise `feedback_cron_success_not_equal_state_mutation.md` to reference the new assertion pattern as the canonical fix.

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-15-supervisor-clog-ranker-requirements.md](../brainstorms/2026-05-15-supervisor-clog-ranker-requirements.md)
- Related workflows: `.github/workflows/pipeline-health.yml`, `.github/workflows/strategy-audit.yml`, `.github/workflows/bot-pr-review-merge.yml`
- Related state files: `company/pipeline-health-state.json`, `company/strategy-audit-baseline.json`
- Related memories: see Context > Institutional Learnings.
- Pulse seed: `docs/pulse-reports/2026-05-15_22-33.md`
