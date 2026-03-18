# Session — Event-driven Loop Automerge and Health Checks

**Date:** 2026-03-18
**Branch:** `task/loop-automerge-event-driven`

## Context

Picked up after 3 days away. Reviewed recent activity (Mar 15-18), inspected GitHub Actions error log, and identified pipeline issues.

## Pickmeup Summary

- Mar 15: Multi-repo observation shipped
- Mar 16: Shared memory subsystem Phase 1+2, observation loop bogus-issue fix
- Mar 17: Autonomous spec validation pipeline, workflow placeholder fixes, coroot outage postmortem, Node.js 24 update
- Mar 18: Daily assessment PR #34 created but not auto-merged

## Actions Log Deep Dive

Reviewed all 30 recent GitHub Actions runs. Found 3 error patterns:

1. **board-sync.yml failures (12 runs)** — RESOLVED. Placeholder env vars + `env.` context not available in job-level `if`. Fixed by moving to `workflow-templates/`.
2. **goose-build.yml failures (8 runs)** — RESOLVED. Invalid `uses: __SETUP_ACTION__` placeholder. Same fix.
3. **approve-build.yml action_required (1 run)** — Copilot reviewer commenting on non-spec PRs triggers false positives. Cosmetic noise, not blocking.

## PR #34 Dissection

Daily assessment correctly self-promoted from Foundation → Dogfood stage. Loop finally recognized wgmesh is a functional product. Minor run counter drift (8 vs 9 vs 10 across files).

## Why PR #34 Wasn't Auto-merged

The `protect-main` ruleset requires 1 approving review. The observation loop polled for Copilot's review for 90 seconds, but the review arrived ~68 seconds late. No retry mechanism existed.

## Fix 1: Event-driven Loop Automerge

Created `loop-automerge.yml` — triggers on `pull_request_review` for `loop/*` branches. Checks for blocking reviews and inline comments, merges if clean. Removed 43 lines of polling logic from `observation-loop.yml`.

## Fix 2: 15-minute Health Checks

Split concern: strategic assessment (daily, LLM-powered) vs outage detection (15-min, curl-based). Created `health-check.yml` that reuses existing `collect-infra.sh` and `health.json`. Creates GitHub issue on failure, comments on subsequent failures, auto-closes on recovery.

## Deliverables

- PR #35: `feat: event-driven loop automerge + 15-min health checks`
  - `.github/workflows/loop-automerge.yml` (new)
  - `.github/workflows/health-check.yml` (new)
  - `.github/workflows/observation-loop.yml` (simplified)
  - `.github/labels.yml` (added `health-check` label)
- `docs/solutions/integration-issues/loop-pr-automerge-timing-race.md`
- `docs/solutions/design-decisions/split-monitoring-from-assessment.md`
