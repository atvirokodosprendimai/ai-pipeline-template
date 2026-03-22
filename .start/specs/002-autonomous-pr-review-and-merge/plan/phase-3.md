---
title: "Phase 3: Workflow Integration, Testing, and Documentation"
status: pending
version: "1.0"
phase: 3
---

# Phase 3: Workflow Integration, Testing, and Documentation

## Phase Context

**GATE**: Read all referenced files before starting this phase.

**Specification References**:
- `[ref: SDD/Deployment View]` — environment config, rollback strategy
- `[ref: SDD/Building Block View/Directory Map]` — workflow modification
- `[ref: SDD/Cross-Cutting Concepts/Pattern Documentation]` — new pattern doc
- `[ref: SDD/Quality Requirements]` — all quality targets

**Key Decisions**:
- ADR-1: Inline execution — add steps directly to PR-creating workflow
- Env vars passed via workflow `env:` block (SEC-1, SEC-3)
- PUSH_TOKEN for authentication (ARCH-8)
- Concurrency group per PR branch with `cancel-in-progress: false` (ARCH-6)

**Dependencies**:
- Phase 1 + Phase 2 complete (script fully functional)
- Target workflow file must exist (e.g., workflow that creates Goose PRs)

---

## Tasks

Wires the script into the PR-creating workflow, adds comprehensive tests, and creates documentation.

- [ ] **T3.1 Workflow integration** `[activity: ci-cd]`

  1. Prime: Read target PR-creating workflow (e.g., goose-build.yml or approve-build.yml). Read SDD/Deployment View for env var configuration. Read CONSTITUTION.md SEC-1, SEC-3, ARCH-8 for secrets/env patterns. `[ref: SDD/Deployment View/Single Application Deployment]`
  2. Test: Workflow step calls `company/scripts/pr-review-merge.sh`; env block passes GH_TOKEN, TARGET_REPO, PR_NUMBER correctly; permissions block includes required scopes (contents:write, pull-requests:write, issues:write, actions:read); concurrency group set to `pr-review-${{ github.run_id }}` with `cancel-in-progress: false`; optional threshold overrides available via env vars
  3. Implement: Add review-merge step to the workflow YAML after PR creation step. Configure `env:` block with secrets via `${{ secrets.PUSH_TOKEN }}`. Add concurrency group. Ensure step only runs when PR was actually created (conditional on PR creation step output).
  4. Validate: `actionlint` passes on modified workflow; env block follows SEC-1 (no secrets interpolation in run:); permissions are minimal (SEC-4)
  5. Success: Script is callable from workflow `[ref: SDD/Architecture Decisions/ADR-1]`; secrets via env blocks `[ref: CONSTITUTION/SEC-1]`; concurrency configured `[ref: CONSTITUTION/ARCH-6]`

- [ ] **T3.2 Unit test suite** `[activity: testing]` `[parallel: true]`

  1. Prime: Read `company/scripts/test-pipeline.sh` for existing test patterns (PASS/FAIL counters, cleanup trap, pre-flight validation). Read SDD/Quality Requirements for testability requirement. `[ref: SDD/Quality Requirements/Testability]`
  2. Test: Create `company/scripts/test-pr-review-merge.sh` that tests: poll function returns correct exit codes; guardrail functions catch each violation type (6 scenarios from SDD traced walkthrough); escalate function produces correct label + comment + audit entry; merge function handles success/conflict/error; circuit breaker activates at threshold; env var defaults work correctly; manual-only label skips automation
  3. Implement: Write test script following existing conventions: `#!/usr/bin/env bash`, `set -euo pipefail`, `trap cleanup EXIT`, PASS/FAIL counters, pre-flight checks. Mock `gh` CLI calls using a stub script in PATH. Test each function in isolation.
  4. Validate: Test script passes with all PASS, zero FAIL; `shellcheck` passes on test script; test script follows TEST-1 (cleanup trap), TEST-2 (PASS/FAIL output), TEST-3 (pre-flight)
  5. Success:
    - [ ] All guardrail scenarios tested `[ref: PRD/AC-4.1 through AC-4.5]`
    - [ ] Poll timeout behavior tested `[ref: PRD/AC-1.2, AC-1.3]`
    - [ ] Escalation output tested `[ref: PRD/AC-5.1]`
    - [ ] Fix loop retry logic tested `[ref: PRD/AC-3.1, AC-3.3]`

- [ ] **T3.3 E2E test scenarios** `[activity: testing]`

  1. Prime: Read `company/scripts/e2e-pipeline.sh` for existing E2E patterns. Read SDD/Risks and Technical Debt/Implementation Gotchas. `[ref: PRD/Acceptance Criteria — all features]`
  2. Test: Design 4 E2E scenarios: (1) Clean PR: bot creates PR -> Copilot reviews clean -> guardrails pass -> auto-merge; (2) Fix loop: bot PR -> Copilot has comments -> agent re-assigned -> fixed -> merge; (3) Guardrail block: PR too large -> escalated with correct reason; (4) Retry exhaustion: 3 retries -> still has comments -> escalated with history
  3. Implement: Add E2E test scenarios to `company/scripts/e2e-pipeline.sh` (or create `company/scripts/e2e-pr-review.sh`). Use `workflow_dispatch` trigger with test mode. Create test PRs with known characteristics. Poll for expected outcomes.
  4. Validate: All 4 scenarios pass; cleanup removes test artifacts (branches, PRs, labels); follows TEST-1 through TEST-5 constitution rules
  5. Success:
    - [ ] Clean merge E2E passes `[ref: PRD/AC-2.1, AC-2.2]`
    - [ ] Fix loop E2E passes `[ref: PRD/AC-3.1, AC-3.3]`
    - [ ] Guardrail block E2E passes `[ref: PRD/AC-4.1]`
    - [ ] Retry exhaustion E2E passes `[ref: PRD/AC-3.3]`

- [ ] **T3.4 Pattern documentation** `[activity: documentation]` `[parallel: true]`

  1. Prime: Read `docs/patterns/workflow-self-merge.md` for existing pattern doc style. `[ref: SDD/Cross-Cutting Concepts/Pattern Documentation]`
  2. Test: Document covers: when to use, how it works, configuration options, guardrails, escalation paths, and integration example
  3. Implement: Create `docs/patterns/pr-review-merge.md` documenting the autonomous review-merge pattern. Include: problem statement, solution overview, configuration reference (all env vars), guardrail reference, escalation flow, and usage example.
  4. Validate: Document is accurate against implementation; no stale references
  5. Success: Pattern documented for reuse `[ref: SDD/Cross-Cutting Concepts/Pattern Documentation]`

- [ ] **T3.5 Phase 3 Validation (Final)** `[activity: validate]`

  - Run full validation suite: `shellcheck company/scripts/pr-review-merge.sh`, `shellcheck company/scripts/test-pr-review-merge.sh`, `actionlint .github/workflows/*.yml`, `company/scripts/test-pr-review-merge.sh` (unit tests). Verify all PRD acceptance criteria are covered by tests. Verify constitution compliance end-to-end.
  - Success:
    - [ ] All scripts pass `shellcheck` `[ref: CONSTITUTION/QUAL-1]`
    - [ ] All workflows pass `actionlint` `[ref: CONSTITUTION/SEC-4]`
    - [ ] Unit tests: all PASS, zero FAIL `[ref: SDD/Quality Requirements/Testability]`
    - [ ] E2E tests: all 4 scenarios pass `[ref: PRD/Success Metrics]`
    - [ ] Pattern doc created `[ref: SDD/Cross-Cutting Concepts]`
    - [ ] Constitution compliance verified: Andon, SEC-1-4, ARCH-2/4/5/6/8, QUAL-1/2/5/6 `[ref: CONSTITUTION.md]`
