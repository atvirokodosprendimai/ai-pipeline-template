---
tldr: Pull specs from the 7 subsections of the ai-pipeline-template system
status: active
---

# Plan: Pull subsection specs for the full pipeline

## Context

- Overview pull: `memory/pull - 2603230702 - ai pipeline template full system overview.md`
- Goal: Extract a complete eidos spec set from the existing codebase

## Phases

### Phase 1 - Observation Loop (OODA Cycle) - status: open

1. [ ] Pull spec from observation loop
   - `observation-loop.yml`, `collect-github.sh`, `collect-infra.sh`, `collect-contributions.sh`, `collect-memory.sh`, `system-prompt.md`, `loop-state.json`
   - Focus: the OODA cycle, signal collection, LLM assessment, issue creation/closure, funnel tracking
   - Output: `eidos/spec - observation loop - autonomous OODA cycle for company operations.md`

### Phase 2 - Pipeline State Machine - status: open

1. [ ] Pull spec from pipeline state machine
   - `copilot-triage.yml`, `spec-validation.yml`, `approve-build.yml`, `spec-merged-build.yml`, `impl-merged-close.yml`, `copilot-undraft.yml`
   - Focus: label-driven lifecycle, agent roles, transitions, guard conditions
   - Output: `eidos/spec - pipeline state machine - label driven issue lifecycle.md`

### Phase 3 - Self-Healing - status: open

1. [ ] Pull spec from self-healing system
   - `pipeline-health.yml`, `pipeline-health-state.json`
   - Focus: stale detection, recovery actions, circuit breaker, escalation, needs-human auto-close
   - Output: `eidos/spec - self healing - deterministic pipeline recovery.md`

### Phase 4 - Autonomous PR Review and Merge - status: open

1. [ ] Pull spec from PR review and merge
   - `bot-pr-review-merge.yml`, `pr-review-merge.sh`
   - Focus: guardrails (review, size, security, author), escalation, sanitisation
   - Output: `eidos/spec - pr review merge - autonomous bot pr guardrails.md`

### Phase 5 - Infrastructure Monitoring - status: open

1. [ ] Pull spec from infrastructure monitoring
   - `health-check.yml`, `collect-infra.sh`, `health.json`
   - Focus: endpoint health checks, issue lifecycle (create on failure, close on recovery)
   - Output: `eidos/spec - infrastructure monitoring - endpoint health and alerting.md`

### Phase 6 - Security and Quality Framework - status: open

1. [ ] Pull spec from security and quality rules
   - `CONSTITUTION.md`, `sanitise.sh`
   - Focus: Andon principle, enforceable rules, sanitisation, quality patterns
   - Output: `eidos/spec - security quality - constitution and enforcement.md`

### Phase 7 - Testing Infrastructure - status: open

1. [ ] Pull spec from testing infrastructure
   - `test-self-healing-e2e.sh`, `test-pr-review-merge.sh`, `test-collect-memory.sh`, `test-circuit-breaker-e2e.sh`
   - Focus: E2E patterns, cleanup traps, structured output, pre-flight validation
   - Output: `eidos/spec - testing - e2e and integration test framework.md`

## Verification

- Each phase produces a spec in `eidos/` that captures intent, not mechanism
- Specs link to each other via `[[wiki links]]` where subsystems interact
- Running `/eidos:coherence` after all specs should show no contradictions
- Running `/eidos:drift` should show minimal divergence from code

## Adjustments

## Progress Log
