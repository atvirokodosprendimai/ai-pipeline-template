---
title: "Universal Bot PR Review and Merge"
status: draft
version: "1.0"
---

# Implementation Plan

## Context Priming

- `.start/specs/003-universal-bot-pr-review-merge/requirements.md`
- `.start/specs/003-universal-bot-pr-review-merge/solution.md`
- `CONSTITUTION.md` v2.0
- `company/scripts/pr-review-merge.sh` (unchanged, already exists)
- `.github/workflow-templates/pr-review-merge-step.yml` (reference)

**Key Decisions:**
- ADR-1: `pull_request: [opened]` trigger (no `synchronize`)
- ADR-2: Author filter in job `if:` condition
- ADR-3: Remove inline callers from pipeline-health and observation-loop

## Implementation Phases

- [ ] [Phase 1: Universal Workflow and Inline Removal](phase-1.md)

---

## Plan Verification

| Criterion | Status |
|-----------|--------|
| A developer can follow this plan without additional clarification | :white_check_mark: |
| Every task produces a verifiable deliverable | :white_check_mark: |
| All PRD acceptance criteria map to specific tasks | :white_check_mark: |
| Dependencies are explicit | :white_check_mark: |
