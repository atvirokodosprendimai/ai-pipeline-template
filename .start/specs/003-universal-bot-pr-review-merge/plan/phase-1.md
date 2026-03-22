---
title: "Phase 1: Universal Workflow and Inline Removal"
status: completed
version: "1.0"
phase: 1
---

# Phase 1: Universal Workflow and Inline Removal

## Phase Context

**Specification References**:
- `[ref: SDD/Building Block View/Workflow Specification]` — full YAML
- `[ref: SDD/Changes to Existing Workflows]` — what to remove

**Dependencies**:
- `company/scripts/pr-review-merge.sh` exists (spec 002, already on main)
- `company/scripts/sanitise.sh` exists (already on main)

---

## Tasks

- [ ] **T1.1 Create bot-pr-review-merge.yml** `[activity: ci-cd]`

  1. Prime: Read SDD/Workflow Specification for the full YAML. Read CONSTITUTION.md SEC-1, SEC-3, SEC-4, ARCH-8. `[ref: SDD/Building Block View]`
  2. Test: Workflow triggers on `pull_request: [opened]`; job filters to approved bot authors; env block passes GH_TOKEN, TARGET_REPO, PR_NUMBER; permissions are minimal; concurrency group is per-PR with cancel-in-progress: false; step checks out repo and runs `bash company/scripts/pr-review-merge.sh`
  3. Implement: Create `.github/workflows/bot-pr-review-merge.yml` per SDD spec
  4. Validate: YAML parses cleanly; SEC-1 (no secrets in run:); SEC-3 (PR number via env); SEC-4 (explicit permissions)
  5. Success: Workflow created `[ref: PRD/AC-1.1, AC-1.2, AC-1.3]`

- [ ] **T1.2 Remove inline callers** `[activity: ci-cd]` `[parallel: true]`

  1. Prime: Read SDD/Changes to Existing Workflows. Read current pipeline-health.yml and observation-loop.yml to find the inline blocks. `[ref: SDD/Architecture Decisions/ADR-3]`
  2. Test: Inline pr-review-merge.sh calls removed from both workflows; PR creation still works (gh pr create remains); no other functionality affected
  3. Implement: Remove the 4-line review-merge block from pipeline-health.yml (around line 742-745) and observation-loop.yml (around line 394-397)
  4. Validate: Workflows still parse cleanly; PR creation steps untouched; only the review-merge call removed
  5. Success: No inline duplication `[ref: PRD/AC-2.1, AC-3.1]`

- [ ] **T1.3 Phase Validation** `[activity: validate]`

  - Verify: bot-pr-review-merge.yml exists and parses. Inline calls removed from both workflows. Constitution compliance (SEC-1, SEC-3, SEC-4, ARCH-4, ARCH-8). Run `bash -n company/scripts/pr-review-merge.sh` (unchanged, sanity check).
  - Success:
    - [ ] New workflow passes YAML validation
    - [ ] Inline calls removed from pipeline-health.yml and observation-loop.yml
    - [ ] All workflows parse cleanly
    - [ ] Constitution compliance verified
