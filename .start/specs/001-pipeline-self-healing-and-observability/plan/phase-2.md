---
title: "Phase 2: Self-Healing Checks and Circuit Breaker"
status: completed
version: "1.0"
phase: 2
---

# Phase 2: Self-Healing Checks and Circuit Breaker

## Phase Context

**GATE**: Read all referenced files before starting this phase.

**Specification References**:
- `[ref: SDD/Implementation Examples/Stale Triage Detection]` — Core healing pattern with traced walkthrough
- `[ref: SDD/Implementation Examples/Circuit Breaker]` — Per-run safety valve
- `[ref: SDD/Runtime View/Complex Logic]` — Fulfilled needs-human detection algorithm
- `[ref: SDD/Runtime View/Error Handling]` — Error handling for each failure mode
- `[ref: PRD/Feature Requirements/Must Have]` — Features 1-4 (stale detection) + Feature 7 (circuit breaker) + Feature 6 (audit trail)

**Key Decisions**:
- 2-failure escalation threshold (fast escalation, 4h max before needs-human)
- 24h cooldown per issue after escalation
- Per-run circuit breaker: 10 creates or 5 errors → stop
- Content sanitization via `sanitise.sh` before any issue creation
- `manual-only` label exempts issues from self-healing

**Dependencies**:
- Phase 1 complete — workflow skeleton, state files, auto-merge extension

---

## Tasks

Implements all 5 self-healing checks, the circuit breaker, and the audit trail. After this phase, the pipeline autonomously detects and recovers stuck issues, escalates persistent failures, and logs all actions.

- [ ] **T2.1 Stale Triage Detection and Recovery** `[activity: backend-logic]` `[component: ai-pipeline-template]`

  1. Prime: Read SDD implementation example for stale triage `[ref: SDD/Implementation Examples/Stale Triage Detection]`. Read `observation-loop.yml` lines 519-544 for existing stale sweep pattern. Read `copilot-triage.yml` to understand label trigger conditions.
  2. Test: Given issue #42 labeled `needs-triage` for >24h, workflow removes and re-adds label; Given issue #43 labeled `needs-triage` for <24h, workflow skips it; Given issue with `wont-do` label, workflow skips it; Given 2 prior failures, workflow escalates to `needs-human`; Audit log entry created for each action
  3. Implement: Add check step to `pipeline-health.yml` — query stale `needs-triage` issues from wgmesh, check retry tracker, toggle label or escalate, update state, append audit log. Use dual-platform date math. Include `manual-only` label check.
  4. Validate: Step logic matches traced walkthrough in SDD. Audit entries have all required fields (timestamp, run_id, action, issue_number, reason, outcome, retry_count).
  5. Success:
     - Stale triage issues detected and re-triggered `[ref: PRD/AC Feature 1 — criteria 1]`
     - Issues with `wont-do`/`needs-info` skipped `[ref: PRD/AC Feature 1 — criteria 2]`
     - 2-failure escalation creates needs-human `[ref: PRD/AC Feature 1 — criteria 3]`
     - Audit trail logged `[ref: PRD/AC Feature 6 — criteria 1]`

- [ ] **T2.2 Stale Copilot Triaging Recovery** `[activity: backend-logic]` `[component: ai-pipeline-template]` `[parallel: true]`

  1. Prime: Read SDD for copilot triaging check pattern. Read `copilot-triage.yml` for Copilot assignment mechanism. Note: Copilot re-assignment may require label toggle fallback if direct API fails.
  2. Test: Given issue labeled `copilot-triaging` for >48h with no spec PR, Copilot is re-assigned; Given issue where spec PR exists (in progress), issue is skipped; Given 2 consecutive failures, escalation occurs; Audit log entry created
  3. Implement: Add check step to `pipeline-health.yml` — query stale `copilot-triaging` issues, check for linked spec PRs (PR title pattern `spec: Issue #N`), attempt re-assignment with fallback to label toggle (`copilot-triaging` → remove → add `needs-triage`), update retry tracker, append audit
  4. Validate: Logic correctly identifies stale vs in-progress issues. Fallback path works when direct re-assignment fails.
  5. Success:
     - Stale copilot issues detected and retried `[ref: PRD/AC Feature 2 — criteria 1]`
     - In-progress work not disrupted `[ref: PRD/AC Feature 2 — criteria 2]`
     - 2-failure escalation `[ref: PRD/AC Feature 2 — criteria 3]`

- [ ] **T2.3 Stale Build Approval Recovery** `[activity: backend-logic]` `[component: ai-pipeline-template]` `[parallel: true]`

  1. Prime: Read SDD for approved-for-build check. Read `goose-build.yml` (workflow template) for trigger mechanism. Note the guard: `!contains(github.repository, 'ai-pipeline-template')` — cannot trigger Goose from this repo directly. Read `approve-build.yml` for label flow.
  2. Test: Given PR labeled `approved-for-build` for >24h with no impl PR, Goose is re-triggered; Given impl PR already exists, no re-trigger; Given 2 consecutive failures, escalation; Audit log entry
  3. Implement: Add check step — query stale `approved-for-build` PRs, check for linked impl PRs (PR title pattern `impl: Issue #N`), re-trigger via label toggle on PR (remove + re-add `approved-for-build`), update retry tracker, append audit. If label toggle doesn't work for PRs, fall back to `gh workflow run` targeting wgmesh.
  4. Validate: Logic correctly distinguishes stale from in-progress builds. Re-trigger mechanism fires Goose workflow.
  5. Success:
     - Stale approved PRs detected and Goose re-triggered `[ref: PRD/AC Feature 3 — criteria 1]`
     - 2-failure escalation `[ref: PRD/AC Feature 3 — criteria 2]`
     - Existing impl PRs detected `[ref: PRD/AC Feature 3 — criteria 3]`

- [ ] **T2.4 Fulfilled Needs-Human Auto-Close** `[activity: backend-logic]` `[component: ai-pipeline-template]`

  1. Prime: Read SDD Runtime View complex logic algorithm for fulfilled needs-human detection `[ref: SDD/Runtime View/Complex Logic]`. Read `company/loop-state.json`, `company/costs.json`, `company/health.json` to understand available signals.
  2. Test: Given needs-human issue with linked merged PR, issue is closed with reason; Given needs-human about API key where loop now succeeds, issue is closed; Given needs-human with no resolution signals, issue remains open; Audit log entry for each close
  3. Implement: Add check step — query open `needs-human` issues, for each: check linked PRs (merged?), check comments (human resolution?), check title-pattern signals (API key → loop success, health check → endpoints healthy, budget → costs.json updated). Use `sanitise.sh` on close comments. Append audit.
  4. Validate: Signal detection correctly identifies resolved vs unresolved issues. Close comments include clear reasons.
  5. Success:
     - Merged PR signals detected `[ref: PRD/AC Feature 4 — criteria 1]`
     - Condition-based signals detected `[ref: PRD/AC Feature 4 — criteria 2]`
     - Unresolved issues left open `[ref: PRD/AC Feature 4 — criteria 3]`

- [ ] **T2.5 Funnel Signal Reporter** `[activity: backend-logic]` `[component: ai-pipeline-template]` `[parallel: true]`

  1. Prime: Read PRD Could Have Feature 10 for signal detection `[ref: PRD/Feature 10]`. Read SDD ADR-6 — self-healing reports signals, does NOT advance funnel `[ref: SDD/Architecture Decisions/ADR-6]`. Read `company/loop-state.json` for current funnel stage.
  2. Test: Given product repo has CLAUDE.md with Architecture section, `funnel_signals.dogfood` is set to true in state; Given all health.json endpoints respond 200, `funnel_signals.presence` is set to true; Funnel stage in loop-state.json is NOT modified
  3. Implement: Add check step — fetch CLAUDE.md from wgmesh (GitHub contents API), check for Architecture/Build sections. Curl health.json endpoints. Write detected signals to `pipeline-health-state.json` under a `funnel_signals` key. Do NOT touch `loop-state.json`.
  4. Validate: Signals correctly detected. State file updated. loop-state.json unchanged.
  5. Success:
     - Funnel signals reported in state file `[ref: PRD/AC Feature 10 — criteria 1, 2]`
     - loop-state.json not modified `[ref: SDD/ADR-6]`

- [ ] **T2.6 Circuit Breaker** `[activity: backend-logic]` `[component: ai-pipeline-template]`

  1. Prime: Read SDD implementation example for circuit breaker `[ref: SDD/Implementation Examples/Circuit Breaker]`. Read PRD Feature 7 acceptance criteria `[ref: PRD/Feature 7]`.
  2. Test: Given 10 issues created in one run, circuit breaker fires and creates single escalation issue; Given 5 errors in one run, circuit breaker fires; Given circuit breaker triggered, no further processing occurs; Given next cycle after breaker, normal operation resumes (no persistent disabled state); Audit log entry for circuit breaker event
  3. Implement: Add per-run counters at top of workflow (`ACTIONS_TAKEN`, `ERRORS`, `ISSUES_CREATED`). After each check step, call `check_circuit_breaker()` function. If triggered: create single escalation issue, log to audit, exit workflow. Counters reset naturally each run (shell variables).
  4. Validate: Circuit breaker correctly detects threshold breach. Escalation issue created with summary of what happened.
  5. Success:
     - Per-issue 2-failure escalation `[ref: PRD/AC Feature 7 — criteria 1]`
     - Per-run 10/5 threshold `[ref: PRD/AC Feature 7 — criteria 2]`
     - Cooldown + reset `[ref: PRD/AC Feature 7 — criteria 3]`

- [ ] **T2.7 Phase Validation** `[activity: validate]`

  - Run full pipeline-health.yml via `workflow_dispatch`. Verify:
    - All 5 checks execute sequentially without errors
    - State file updated with `last_run_summary` reflecting actual results
    - Audit log has entries for all actions taken (or `no_action` if pipeline is healthy)
    - PR created with state + audit changes
    - No modifications to `loop-state.json`
    - Circuit breaker logic testable by creating artificial stale issues
