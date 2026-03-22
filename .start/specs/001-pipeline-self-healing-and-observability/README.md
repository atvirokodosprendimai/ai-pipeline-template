# Specification: 001-pipeline-self-healing-and-observability

## Status

| Field | Value |
|-------|-------|
| **Created** | 2026-03-21 |
| **Current Phase** | Ready |
| **Last Updated** | 2026-03-21 |
| **Mode** | Agent Team |

## Documents

| Document | Status | Notes |
|----------|--------|-------|
| requirements.md | completed | Approved 2026-03-21 |
| solution.md | completed | Approved 2026-03-21 |
| plan/ | completed | Approved 2026-03-22 |

**Status values**: `pending` | `in_progress` | `completed` | `skipped`

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-21 | Unified feature (self-healing + observability) | Dashboard makes self-healing visible and debuggable |
| 2026-03-21 | Hybrid approach: separate workflow + chimney dashboard | Deterministic self-healing on 2h interval, LLM assessment stays at 8h |
| 2026-03-21 | Fully autonomous self-healing | Log everything, don't ask permission. Humans review via dashboard |
| 2026-03-21 | No funnel stage demotion | Transient outages shouldn't regress the funnel |
| 2026-03-21 | 24h yellow / 48h red thresholds | Matches self-healing intervention intervals |
| 2026-03-21 | Start with PRD | Full specification workflow: PRD → SDD → PLAN |
| 2026-03-21 | Agent Team mode | Complex domain with 3 phases, multiple integrations (GitHub Actions, chimney, loop-state) |
| 2026-03-21 | Observation loop owns funnel advancement | Self-healing detects signals but reports only; LLM loop makes advancement decisions. Avoids state conflicts |
| 2026-03-21 | Chimney uses GitHub API direct | Dashboard queries GitHub API with 15-min cache. Zero new infra. No push API needed |
| 2026-03-21 | 2-failure escalation threshold | Fast escalation to needs-human after 2 consecutive failures (4h window) |
| 2026-03-21 | Public dashboard, no auth | Open by design — filtered data (no assessment narratives or strategy details) |
| 2026-03-21 | PRD approved | 11 features, 28 acceptance criteria, 3 open questions deferred to SDD |
| 2026-03-21 | ADR-1: JSON file in repo | State in pipeline-health-state.json, matches observation-loop pattern |
| 2026-03-21 | ADR-2: JSONL audit trail | Append-only audit-log.jsonl, committed with state changes |
| 2026-03-21 | ADR-3: PR to main | Branch pipeline-health/{date}, auto-mergeable, reviewable |
| 2026-03-21 | ADR-4: Hardcoded thresholds | 24h yellow / 48h red constants in chimney code |
| 2026-03-21 | SDD approved | 6 ADRs confirmed, 12 EARS acceptance criteria, implementation examples with traced walkthroughs |
| 2026-03-22 | PLAN approved | 4 phases, 25 tasks, 7 parallel opportunities, full PRD coverage matrix |
| 2026-03-22 | Specification finalized | PRD + SDD + PLAN all complete. Ready for implementation. |

## Context

Brainstorm: .start/ideas/2026-03-21-pipeline-self-healing-and-observability.md

The AI pipeline currently relies on LLM-based observation loop for board hygiene and manual human intervention for funnel stage advancement and stale state detection. This session's RCA work proved LLMs are unreliable for mechanical tasks. This spec defines deterministic self-healing and a chimney-based pipeline dashboard.

---
*This file is managed by the specify-meta skill.*
