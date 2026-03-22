---
title: "Autonomous PR Review and Merge"
status: draft
version: "1.0"
---

# Implementation Plan

## Validation Checklist

### CRITICAL GATES (Must Pass)

- [x] All `[NEEDS CLARIFICATION: ...]` markers have been addressed
- [x] All specification file paths are correct and exist
- [x] Each phase follows TDD: Prime -> Test -> Implement -> Validate
- [x] Every task has verifiable success criteria
- [x] A developer could follow this plan independently

### QUALITY CHECKS (Should Pass)

- [x] Context priming section is complete
- [x] All implementation phases are defined with linked phase files
- [x] Dependencies between phases are clear (no circular dependencies)
- [x] Parallel work is properly tagged with `[parallel: true]`
- [x] Activity hints provided for specialist selection `[activity: type]`
- [x] Every phase references relevant SDD sections
- [x] Every test references PRD acceptance criteria
- [x] Integration & E2E tests defined in final phase
- [x] Project commands match actual project setup

---

## Context Priming

*GATE: Read all files in this section before starting any implementation.*

**Specification**:

- `.start/specs/002-autonomous-pr-review-and-merge/requirements.md` — Product Requirements (28 acceptance criteria)
- `.start/specs/002-autonomous-pr-review-and-merge/solution.md` — Solution Design (6 ADRs, all confirmed)
- `.start/ideas/2026-03-22-autonomous-pr-review-and-merge.md` — Original brainstorm
- `CONSTITUTION.md` — Governance rules (must comply with all L1/L2)
- `docs/patterns/workflow-self-merge.md` — Existing self-merge pattern to reuse
- `docs/solutions/integration-issues/github-app-reviews-dont-trigger-workflows.md` — Why we poll

**Key Design Decisions**:

- **ADR-1**: Inline execution — review-merge runs as steps within the PR-creating workflow (zero queue delay)
- **ADR-2**: Single script — all logic in `company/scripts/pr-review-merge.sh` (ARCH-2 compliance)
- **ADR-3**: Ephemeral state — retry counter lives within workflow run, no state files
- **ADR-4**: Squash merge — `gh pr merge --squash --admin --delete-branch`
- **ADR-5**: Never merge without review — timeout after 6 min -> escalate
- **ADR-6**: Honor manual-only label — skip all automation when present

**Implementation Context**:

```bash
# Testing
company/scripts/test-pipeline.sh       # Unit/integration tests
company/scripts/e2e-pipeline.sh        # End-to-end tests

# Quality
shellcheck company/scripts/*.sh        # Shell linting
actionlint .github/workflows/*.yml     # Workflow linting

# Sanitisation
company/scripts/sanitise.sh            # Content sanitisation (SEC-2)
```

---

## Implementation Phases

Each phase is defined in a separate file. Tasks follow red-green-refactor: **Prime** (understand context), **Test** (red), **Implement** (green), **Validate** (refactor + verify).

- [x] [Phase 1: Core Script Foundation](phase-1.md)
- [x] [Phase 2: Fix Loop and Retry Orchestration](phase-2.md)
- [x] [Phase 3: Workflow Integration, Testing, and Documentation](phase-3.md)

---

## Plan Verification

Before this plan is ready for implementation, verify:

| Criterion | Status |
|-----------|--------|
| A developer can follow this plan without additional clarification | :white_check_mark: |
| Every task produces a verifiable deliverable | :white_check_mark: |
| All PRD acceptance criteria map to specific tasks | :white_check_mark: |
| All SDD components have implementation tasks | :white_check_mark: |
| Dependencies are explicit with no circular references | :white_check_mark: |
| Parallel opportunities are marked with `[parallel: true]` | :white_check_mark: |
| Each task has specification references `[ref: ...]` | :white_check_mark: |
| Project commands in Context Priming are accurate | :white_check_mark: |
| All phase files exist and are linked from this manifest as `[Phase N: Title](phase-N.md)` | :white_check_mark: |
