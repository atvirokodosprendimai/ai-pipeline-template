---
title: "Pipeline Self-Healing and Observability"
status: draft
version: "1.0"
---

# Implementation Plan

## Validation Checklist

### CRITICAL GATES (Must Pass)

- [x] All `[NEEDS CLARIFICATION: ...]` markers have been addressed
- [x] All specification file paths are correct and exist
- [x] Each phase follows TDD: Prime → Test → Implement → Validate
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

- `.start/specs/001-pipeline-self-healing-and-observability/requirements.md` — Product Requirements (11 features, 28 acceptance criteria)
- `.start/specs/001-pipeline-self-healing-and-observability/solution.md` — Solution Design (6 ADRs, 12 EARS criteria, implementation examples)
- `.start/ideas/2026-03-21-pipeline-self-healing-and-observability.md` — Brainstorm with key decisions

**Key Design Decisions**:

- **ADR-1**: State in JSON file — `company/pipeline-health-state.json` committed via PR, matches observation-loop pattern
- **ADR-2**: JSONL audit trail — `company/audit-log.jsonl` append-only, committed with state
- **ADR-3**: PR to main — branch `pipeline-health/{date}-{run_id}`, auto-mergeable
- **ADR-4**: Hardcoded thresholds — 24h yellow / 48h red constants in chimney code
- **ADR-5**: GitHub API direct — dashboard queries GitHub API with 15-min cache
- **ADR-6**: Observation loop owns funnel — self-healing reports signals, doesn't advance

**Implementation Context**:

```bash
# ai-pipeline-template (this repo)
# Validate YAML syntax
yamllint .github/workflows/pipeline-health.yml  # if installed

# Validate spec
bash .github/scripts/validate-spec.sh specs/

# Test scripts
bash company/scripts/test-collect-memory.sh

# chimney (separate repo — commands TBD during Phase 3)
```

---

## Implementation Phases

Each phase is defined in a separate file. Tasks follow red-green-refactor: **Prime** (understand context), **Test** (red), **Implement** (green), **Validate** (refactor + verify).

> **Tracking Principle**: Track logical units that produce verifiable outcomes. The TDD cycle is the method, not separate tracked items.

- [x] [Phase 1: Foundation — State Files and Workflow Skeleton](phase-1.md)
- [x] [Phase 2: Self-Healing Checks and Circuit Breaker](phase-2.md)
- [ ] [Phase 3: Pipeline Dashboard](phase-3.md)
- [ ] [Phase 4: Integration and Validation](phase-4.md)

---

## Plan Verification

Before this plan is ready for implementation, verify:

| Criterion | Status |
|-----------|--------|
| A developer can follow this plan without additional clarification | ✅ |
| Every task produces a verifiable deliverable | ✅ |
| All PRD acceptance criteria map to specific tasks | ✅ |
| All SDD components have implementation tasks | ✅ |
| Dependencies are explicit with no circular references | ✅ |
| Parallel opportunities are marked with `[parallel: true]` | ✅ |
| Each task has specification references `[ref: ...]` | ✅ |
| Project commands in Context Priming are accurate | ✅ |
| All phase files exist and are linked from this manifest as `[Phase N: Title](phase-N.md)` | ✅ |
