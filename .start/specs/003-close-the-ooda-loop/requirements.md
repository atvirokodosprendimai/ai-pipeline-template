---
title: "Close the OODA Loop"
status: draft
version: "1.0"
---

# Product Requirements Document

## Product Overview

### Vision

The system autonomously drives toward $100K ARR. Humans set the goal, the system executes the full OODA loop — observe, orient, decide, act — with zero manual gates.

### Problem Statement

The OODA loop has four broken transitions:

1. **spec-validation skips in this repo** — the `if: !contains('ai-pipeline-template')` guard means spec PRs in the pipeline template itself don't get auto-approved. The pipeline can't improve itself.

2. **Spec PR approved but not merged** — spec-validation adds `approved-for-build` label, but nobody merges the spec PR. The spec sits open. The build agent needs the spec on main to implement it, but the spec is stuck in a PR.

3. **No build trigger** — `goose-build.yml` is referenced but doesn't exist. When a spec gets `approved-for-build`, nothing happens. The implementation step is completely missing.

4. **No issue closure** — when an implementation PR merges, nobody closes the originating issue. The loop never returns to observe.

### Value Proposition

Close all four gaps in one spec. After this, an issue created by the observation loop flows through spec → build → merge → close with zero human intervention. The loop returns to observe.

## Feature Requirements

### Must Have

#### Feature 1: Enable spec-validation in template repo

- **Acceptance Criteria:**
  - [ ] Given a spec PR is opened in ai-pipeline-template, When spec-validation triggers, Then it runs (no repo name skip)

#### Feature 2: Auto-merge approved spec PRs

- **Acceptance Criteria:**
  - [ ] Given a spec PR passes validation and gets `approved-for-build`, When the label is applied, Then the spec PR is merged to main (via pr-review-merge.sh or direct merge)
  - [ ] Given a spec PR fails validation, When `spec-needs-fix` is applied, Then the spec PR is NOT merged

#### Feature 3: Build trigger workflow

- **Acceptance Criteria:**
  - [ ] Given a spec PR merges to main, When the merge is detected, Then copilot-swe-agent is assigned to the original issue with implementation instructions referencing the merged spec
  - [ ] Given no issue number can be extracted from the spec PR, When the trigger fires, Then it logs a warning and skips (no crash)

#### Feature 4: Universal bot PR review-merge

- **Acceptance Criteria:**
  - [ ] Given any bot-authored PR is opened, When the pull_request event fires, Then pr-review-merge.sh runs (subsumes spec 003-universal)

#### Feature 5: Issue closure on impl merge

- **Acceptance Criteria:**
  - [ ] Given an implementation PR merges, When the merge event fires, Then the linked issue is closed with a comment referencing the merged PR
  - [ ] Given no issue number can be extracted from the PR, When the trigger fires, Then it skips gracefully

### Won't Have

- Cross-repo loop (wgmesh implementation triggers are separate — this spec closes the loop within the template repo)
- Human notification on closure (the audit log is sufficient)
- Rollback automation (if a merged impl breaks something, the next observe cycle catches it)

## Success Metrics

- An issue created with `needs-triage` label reaches closed state with merged implementation PR — zero human intervention
- Time from issue creation to issue closure < 1 hour (dominated by agent work time, not wait time)
- Zero issues stuck in intermediate states for > 24 hours

## Constraints

- CONSTITUTION v2.0 compliance
- All existing guardrails in pr-review-merge.sh apply
- Must work for both template repo (self-improvement) and target repos (wgmesh)
