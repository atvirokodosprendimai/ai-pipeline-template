---
title: "Phase 1: Foundation — State Files and Workflow Skeleton"
status: pending
version: "1.0"
phase: 1
---

# Phase 1: Foundation — State Files and Workflow Skeleton

## Phase Context

**GATE**: Read all referenced files before starting this phase.

**Specification References**:
- `[ref: SDD/Constraints]` — CON-1 through CON-6
- `[ref: SDD/Building Block View/Directory Map]` — file locations
- `[ref: SDD/Interface Specifications/Data Storage Changes]` — state file schemas
- `[ref: SDD/Architecture Decisions]` — ADR-1 (state storage), ADR-2 (audit trail), ADR-3 (PR to main)

**Key Decisions**:
- ADR-1: State stored in `company/pipeline-health-state.json`
- ADR-2: Audit trail in `company/audit-log.jsonl`
- ADR-3: State committed via PR to main (branch `pipeline-health/{date}-{run_id}`)

**Dependencies**:
- None — this is the foundation phase

---

## Tasks

Establishes the state management layer and workflow skeleton. After this phase, the self-healing workflow runs on schedule, reads/writes state, and commits via PR — but does not yet perform any healing checks.

- [ ] **T1.1 Pipeline Health State File** `[activity: data-architecture]` `[component: ai-pipeline-template]`

  1. Prime: Read SDD Data Storage Changes for `pipeline-health-state.json` schema `[ref: SDD/Interface Specifications/Data Storage Changes]`
  2. Test: Validate JSON schema — `last_check` is valid ISO 8601; `retry_tracker` is an object; `last_run_summary` fields are integers; file is valid JSON after jq round-trip
  3. Implement: Create `company/pipeline-health-state.json` with initial empty state:
     ```json
     {
       "last_check": null,
       "check_interval_hours": 2,
       "checks_run": 0,
       "issues_healed_total": 0,
       "retry_tracker": {},
       "last_run_summary": {
         "stale_triage_found": 0,
         "stale_copilot_found": 0,
         "stale_approved_found": 0,
         "needs_human_closed": 0,
         "actions_taken": 0,
         "errors": 0
       }
     }
     ```
  4. Validate: `jq . company/pipeline-health-state.json` succeeds; all fields present with correct types
  5. Success: State file exists, is valid JSON, matches SDD schema `[ref: SDD/Data Storage Changes]`

- [ ] **T1.2 Audit Log File** `[activity: data-architecture]` `[component: ai-pipeline-template]` `[parallel: true]`

  1. Prime: Read SDD Data Storage Changes for `audit-log.jsonl` schema `[ref: SDD/Interface Specifications/Data Storage Changes]`
  2. Test: Validate JSONL format — each line is valid JSON; `timestamp`, `action`, `outcome` fields present; file can be parsed with `jq -s '.' company/audit-log.jsonl`
  3. Implement: Create empty `company/audit-log.jsonl` (empty file, will be appended to)
  4. Validate: File exists; `wc -l` returns 0; appending a test line and parsing with jq works
  5. Success: Audit log file exists, JSONL-appendable `[ref: SDD/Data Storage Changes]`

- [ ] **T1.3 Workflow Skeleton** `[activity: ci-cd]` `[component: ai-pipeline-template]`

  1. Prime: Read observation-loop.yml for permissions, concurrency, commit patterns `[ref: SDD/Implementation Context/Code Context]`. Read SDD Runtime View sequence diagram `[ref: SDD/Runtime View/Primary Flow]`
  2. Test: Workflow YAML is valid; `yamllint` passes (if available); cron schedule `0 */2 * * *` is correct; permissions are minimal (`contents: write, issues: write, pull-requests: write, actions: read`); concurrency group is `pipeline-health` (separate from `observation-loop`)
  3. Implement: Create `.github/workflows/pipeline-health.yml` with:
     - Schedule: `cron: '0 */2 * * *'` + `workflow_dispatch`
     - Permissions: `contents: write`, `issues: write`, `pull-requests: write`, `actions: read`
     - Concurrency: group `pipeline-health`, cancel-in-progress: false
     - Steps: checkout → read state → placeholder for checks → update state summary → commit via PR
     - Commit pattern: reuse observation-loop's branch/PR/push pattern with `pipeline-health/` prefix
     - Bot identity: `pipeline-health[bot]`
  4. Validate: YAML syntax valid; workflow would trigger on cron and manual dispatch; commit step uses `git diff --cached --quiet` guard; PR creation uses `gh pr create`
  5. Success:
     - Workflow file exists at `.github/workflows/pipeline-health.yml` `[ref: SDD/Building Block View/Directory Map]`
     - Schedule is every 2h `[ref: PRD/Feature 1]`
     - Permissions are minimal `[ref: SDD/Cross-Cutting Concepts/System-Wide Patterns]`
     - State is committed via PR `[ref: SDD/Architecture Decisions/ADR-3]`

- [ ] **T1.4 Extend Auto-Merge for Pipeline Health PRs** `[activity: ci-cd]` `[component: ai-pipeline-template]`

  1. Prime: Read `loop-automerge.yml` — it only merges `loop/*` branches `[ref: SDD/Risks and Technical Debt/Implementation Gotchas]`
  2. Test: After modification, PRs from `pipeline-health/*` branches are also auto-merged; existing `loop/*` auto-merge still works
  3. Implement: Update `.github/workflows/loop-automerge.yml` to also match `pipeline-health/*` branch prefix in the head ref filter
  4. Validate: Both `loop/assessment-*` and `pipeline-health/*` patterns match the updated filter; no other branch patterns accidentally included
  5. Success: Pipeline health PRs will auto-merge when reviewed `[ref: SDD/Runtime View/Primary Flow]`

- [ ] **T1.5 Phase Validation** `[activity: validate]`

  - Run all Phase 1 validations. Verify:
    - `company/pipeline-health-state.json` exists and is valid JSON matching schema
    - `company/audit-log.jsonl` exists as empty file
    - `.github/workflows/pipeline-health.yml` has valid YAML syntax
    - `loop-automerge.yml` matches both `loop/*` and `pipeline-health/*` patterns
    - Manual `workflow_dispatch` trigger of pipeline-health.yml would not error (dry-run logic check)
