---
title: "Pipeline Self-Healing and Observability"
date: 2026-03-21
status: brainstormed
tags: [pipeline, self-healing, observability, chimney, dashboard]
---

# Pipeline Self-Healing and Observability

## What We're Building

A unified feature that makes the AI pipeline self-aware and self-correcting:

1. **Pipeline Health Workflow** (`pipeline-health.yml`) — deterministic self-healing that runs every 2h, independent of the LLM-based observation loop. Detects stale states, retries failed triages, auto-advances funnel stage based on real signals.

2. **Pipeline Dashboard** (chimney `/pipeline` endpoint) — Kanban-style view of every issue's position in the pipeline flow, with health indicators and funnel stage banner.

## Why This Approach

- **Deterministic over LLM-driven.** We proved in this session that LLMs are unreliable for mechanical tasks (missed reconciliation, ignored compounding signals). Self-healing must be code, not prompts.
- **Separate workflow over loop-native.** The observation loop runs every 8h for LLM assessment. Self-healing needs faster response (2h) and shouldn't be blocked by LLM API failures.
- **Chimney over new infra.** Chimney already caches GitHub API data and serves a web UI. Adding a pipeline view is incremental, zero new infra cost.

## Key Decisions

1. **Self-healing is deterministic, not LLM-dependent.** Shell/JS in GitHub Actions, no API calls to LLMs.
2. **Runs every 2h** on its own schedule, independent of the 8h observation loop.
3. **Fully autonomous** — auto-fixes all stale states, auto-advances funnel stage. Logs everything, doesn't ask permission. Humans review via dashboard.
4. **Dashboard extends chimney** at `/pipeline` route. No new services.
5. **All 4 signal types** used for funnel advancement: codebase completeness, usage, infrastructure presence, revenue.

## Self-Healing Checks

| Check | Signal | Action | Threshold |
|-------|--------|--------|-----------|
| Stale `needs-triage` | Label age, no assignee | Re-cycle label to re-trigger triage | >24h |
| Stale `copilot-triaging` | Label age, no spec PR from Copilot | Re-assign Copilot, comment on issue | >48h |
| Stale `approved-for-build` | Label age, no impl PR from Goose | Re-trigger goose-build workflow | >24h |
| Fulfilled `needs-human` | Compare title against loop-state.json, costs.json, health signals | Close with reason | Every run |
| Funnel stage drift | Codebase summary + health + usage + revenue signals | Update loop-state.json | Every run |

## Funnel Auto-Advance Logic

| Transition | Signal | How to Check |
|-----------|--------|-------------|
| Foundation → Dogfood | Core features in codebase | CLAUDE.md has architecture/packages sections |
| Dogfood → Presence | Landing page live + quickstart | Health check on chimney.beerpub.dev passes + README has quickstart |
| Presence → Reachable | Billing endpoint live | Health check on billing/payment URL passes |
| Reachable → Pipeline | Revenue tracking active | costs.json revenue field is non-null |
| Pipeline → Revenue | Paying customer retained | Revenue field shows active customer 30+ days |

## Chimney Pipeline View

- **Route:** `/pipeline`
- **Columns:** Created → Triaging → Spec PR → Approved → Implementing → Merged
- **Column mapping:** `needs-triage` → Created, `copilot-triaging` → Triaging, spec PR open → Spec PR, `approved-for-build` → Approved, `goose-implementation` → Implementing, PR merged → Merged
- **Health indicators:** Green (<threshold), Yellow (approaching), Red (>threshold) per column based on age
- **Banner:** Current funnel stage + runway (months remaining) + last loop assessment timestamp

## Resolved Questions

- **Landing page URL:** chimney.beerpub.dev serves as the product landing/dashboard page.
- **Auto-demotion:** No. Once a stage is reached, it stays. Transient outages don't regress the funnel — the loop flags issues but doesn't demote.
- **Health thresholds:** 24h yellow, 48h red. Matches self-healing intervention intervals.

## Parking Lot

(Empty — no scope creep during brainstorming)
