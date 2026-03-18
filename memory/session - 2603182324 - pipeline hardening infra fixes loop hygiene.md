# Session — Pipeline Hardening, Infra Fixes, Loop Hygiene

**Date:** 2026-03-18
**Branches:** `task/loop-automerge-event-driven`, `task/loop-issue-hygiene`, `task/fix-health-endpoints`, `task/fix-health-urls`, `task/compound-infra-phantom-outages`

## Context

Picked up after 3 days away. Reviewed action log, diagnosed pipeline issues, fixed infra "outages", and hardened the observation loop.

## Delivered

### 1. Event-driven loop automerge (PR #35)
- Replaced 90s polling loop with `loop-automerge.yml` triggered by `pull_request_review` events
- Removed 43 lines of polling logic from observation-loop.yml
- Root cause: PR #34 wasn't auto-merged because Copilot reviewed 68s after the 90s window

### 2. 15-minute health checks
- New `health-check.yml` workflow — curls endpoints every 15 min
- Creates GitHub issue on failure, auto-closes on recovery
- Separation of concerns: monitoring (15 min) vs strategic assessment (daily)

### 3. Loop issue/PR hygiene
- System prompt: added hygiene guidance — when to close issues and PRs
- Output schema: added `prs_to_close` field
- Data injection: open issues + PRs list now fed to LLM each run
- Action step: new "Close PRs from assessment" step

### 4. Infrastructure "outage" resolution
- `coroot.beerpub.dev` → wrong URL, should be `table.beerpub.dev` (Cloudflare 530)
- `tvcentras.lt` → wrong URL, should be `tv.beerpub.dev`
- `creu.lt` → defunct domain, removed
- All containers were healthy — phantom outages from bad health.json
- Created `restart-services.yml` workflow in coroot-cicd (useful for future)
- Recreated all coroot containers (confirmed healthy)

### 5. Merged PR #34
- Daily assessment with stage promotion Foundation → Dogfood

## Compound Solutions Documented
- `docs/solutions/integration-issues/loop-pr-automerge-timing-race.md`
- `docs/solutions/design-decisions/split-monitoring-from-assessment.md`
- `docs/solutions/integration-issues/phantom-infra-outages-from-wrong-health-urls.md`

## Still Open
- wgmesh #457: NAT relay flapping — the real product bug, untouched this session
- Loop hygiene: next run should auto-close bogus issues/PRs (#456, #459, #462, #460, #461, #463, #450)
- wgmesh backlog: service registration CLI, protobuf migration, chimney split, etc.
