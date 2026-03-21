# Specification: 001-pipeline-self-healing-and-observability

## Status

| Field | Value |
|-------|-------|
| **Created** | 2026-03-21 |
| **Current Phase** | Initialization |
| **Last Updated** | 2026-03-21 |

## Documents

| Document | Status | Notes |
|----------|--------|-------|
| requirements.md | pending | |
| solution.md | pending | |
| plan/ | pending | |

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

## Context

Brainstorm: .start/ideas/2026-03-21-pipeline-self-healing-and-observability.md

The AI pipeline currently relies on LLM-based observation loop for board hygiene and manual human intervention for funnel stage advancement and stale state detection. This session's RCA work proved LLMs are unreliable for mechanical tasks. This spec defines deterministic self-healing and a chimney-based pipeline dashboard.

---
*This file is managed by the specify-meta skill.*
