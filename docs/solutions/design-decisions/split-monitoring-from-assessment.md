---
title: "Split health monitoring from daily observation loop"
category: design-decisions
date: 2026-03-18
tags: [github-actions, health-check, observation-loop, monitoring, separation-of-concerns]
---

## Problem

Infrastructure outages (coroot 530, tvcentras, creu connection errors) were only surfaced by the daily observation loop — meaning a 24-hour detection window at worst. The loop assessment on 2026-03-18 flagged these outages, but coroot had already been down for 42+ hours before the previous assessment caught it.

## Root Cause

The observation loop conflated two concerns with different cadence requirements:

| Concern | Right cadence | Was running at |
|---------|---------------|----------------|
| Strategic assessment (what to build, blockers, priorities) | Daily | Daily |
| Outage detection (is infrastructure up?) | Minutes | Daily |

Running the full LLM-powered assessment more frequently would waste API budget on strategic analysis that only changes day-to-day.

## Solution

Created a lightweight `health-check.yml` workflow that runs every 15 minutes:

- Reuses existing `company/scripts/collect-infra.sh` and `company/health.json` (no new infrastructure)
- Creates a GitHub issue with `health-check` label on first failure
- Adds comments on subsequent check failures (no duplicate issues)
- Auto-closes the issue when all endpoints recover
- No LLM calls — just `curl` + `gh issue` management

The observation loop continues running daily for strategic assessment, undisturbed.

## Prevention

- When a workflow serves multiple concerns, evaluate whether they need different cadences before adding complexity to a single workflow.
- Lightweight health checks (HTTP status codes) should never depend on LLM availability or API budgets.
