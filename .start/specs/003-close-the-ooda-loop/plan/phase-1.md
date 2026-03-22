---
title: "Phase 1: Close Every Gap"
status: pending
version: "1.0"
phase: 1
---

# Phase 1: Close Every Gap

## Tasks

- [ ] **T1.1 Remove template repo skip from spec-validation** `[activity: ci-cd]`

  1. Prime: Read `.github/workflows/spec-validation.yml` line 19
  2. Implement: Remove the `if: "!contains(github.repository, 'ai-pipeline-template')"` line from the validate job
  3. Validate: YAML valid
  4. Success: spec-validation runs in template repo `[ref: PRD/Feature 1]`

- [ ] **T1.2 Create bot-pr-review-merge.yml** `[activity: ci-cd]` `[parallel: true]`

  1. Prime: Read SDD section 4 (universal bot PR review-merge)
  2. Implement: Create `.github/workflows/bot-pr-review-merge.yml` — triggers on `pull_request: [opened]`, filters to bot authors, calls `bash company/scripts/pr-review-merge.sh`
  3. Validate: YAML valid, SEC-1/3/4 compliant
  4. Success: All bot PRs get autonomous review-merge `[ref: PRD/Feature 4]`

- [ ] **T1.3 Remove inline pr-review-merge.sh calls** `[activity: ci-cd]` `[parallel: true]`

  1. Prime: Read current pipeline-health.yml and observation-loop.yml
  2. Implement: Replace inline 4-line review-merge blocks with comment: `# Review-merge handled by bot-pr-review-merge.yml workflow`
  3. Validate: YAML valid, PR creation steps untouched
  4. Success: No duplicate processing `[ref: PRD/Feature 4]`

- [ ] **T1.4 Create spec-merged-build.yml** `[activity: ci-cd]` `[parallel: true]`

  1. Prime: Read SDD section 3 (build trigger)
  2. Implement: Create `.github/workflows/spec-merged-build.yml` — triggers on `pull_request: [closed]` for merged spec PRs, assigns copilot-swe-agent to original issue with implementation instructions
  3. Validate: YAML valid, uses PUSH_TOKEN, X-GitHub-Api-Version header present
  4. Success: Spec merge triggers implementation `[ref: PRD/Feature 3]`

- [ ] **T1.5 Create impl-merged-close.yml** `[activity: ci-cd]` `[parallel: true]`

  1. Prime: Read SDD section 5 (issue closure)
  2. Implement: Create `.github/workflows/impl-merged-close.yml` — triggers on `pull_request: [closed]` for merged impl PRs, closes linked issue
  3. Validate: YAML valid, filters out spec:/heal:/loop: PRs
  4. Success: Issue closed on impl merge `[ref: PRD/Feature 5]`

- [ ] **T1.6 Add spec-needs-fix escalation to pr-review-merge.sh** `[activity: backend-scripting]`

  1. Prime: Read SDD section 6 (script change)
  2. Implement: After guardrails pass, before merge, check if PR has `spec-needs-fix` label. If yes, escalate with "spec validation failed"
  3. Validate: bash -n passes, existing tests still pass
  4. Success: Spec PRs that fail validation don't merge `[ref: PRD/Feature 2]`

- [ ] **T1.7 Update README.md** `[activity: documentation]`

  1. Implement: Update the loop diagram in README.md to show zero human gates. Change "HUMAN approves" and "HUMAN merges" to automated steps.
  2. Success: README reflects reality

- [ ] **T1.8 Phase Validation** `[activity: validate]`

  - All new workflows parse as valid YAML
  - Inline callers removed
  - pr-review-merge.sh passes bash -n and existing tests
  - README updated
  - Constitution compliance verified
