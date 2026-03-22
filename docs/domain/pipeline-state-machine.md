# Pipeline Issue State Machine

> **Category:** Domain/Business Rules
> **Last Updated:** 2026-03-22
> **Status:** Active

## Overview

This document defines the state machine governing how issues flow through the automated AI pipeline from creation to merge. The pipeline is fully autonomous: GitHub issues are triaged by Copilot, specs are reviewed and approved by a human, and implementations are built by Goose. A self-healing workflow (`pipeline-health.yml`) runs every 2 hours to detect and recover stalled issues, with a circuit breaker to prevent runaway retries.

**Scope:** Issues in `atvirokodosprendimai/wgmesh`, monitored from the `ai-pipeline-template` repository via cross-repo PAT.

## Core Concepts

- **Label-driven state:** Each pipeline stage is represented by a GitHub label. An issue's current label determines its position in the pipeline.
- **Self-healing:** Deterministic (code, not LLM) recovery that detects stale issues and re-triggers the responsible workflow by toggling labels.
- **Circuit breaker:** Safety mechanism that stops self-healing from entering infinite retry loops.
- **Dashboard columns:** The chimney dashboard (`/pipeline`) maps labels to Kanban columns for at-a-glance visibility.
- **Audit trail:** Every self-healing action is logged to `company/audit-log.jsonl` with timestamp, action type, issue number, and reason.

## Business Rules

### Label Precedence

When an issue carries conflicting labels (e.g., both `needs-triage` and `copilot-triaging`), the issue is displayed in the **more advanced** stage. The pipeline is strictly forward-progressing under normal operation.

### Exclusion Labels

Issues carrying any of the following labels are **exempt from self-healing** entirely:

| Label | Meaning |
|-------|---------|
| `manual-only` | Human-managed; self-healing must never touch this issue |
| `wont-do` | Deliberately declined; not stale |
| `needs-info` | Blocked on external input; not stale |

Self-healing skips these issues during every check, regardless of age.

### Schedule

The self-healing workflow runs on a fixed schedule: `0 */2 * * *` (every 2 hours, on the hour). It can also be triggered manually via `workflow_dispatch`.

### State File Ownership

Self-healing writes **only** to `company/pipeline-health-state.json`. It never modifies `company/loop-state.json`, which is owned by the observation loop.

## States and Transitions

### Label State Machine

```
                                  EXCLUSION LABELS
                                  (manual-only, wont-do, needs-info)
                                  exempt issue from self-healing
                                        |
                                        v
  +--------------+    Copilot     +------------------+    Spec PR     +------------+
  | needs-triage | ------------> | copilot-triaging  | ------------> | spec-ready |
  |              |    assigns     | (copilot-revising)|   opened      |            |
  +--------------+    itself      +------------------+               +------------+
        |                               |                                  |
        | stale >24h                    | stale >48h                       | human
        | self-heal:                    | self-heal:                       | approves
        | toggle label                  | reset to needs-triage            |
        v                               v                                  v
  (retry or escalate)           (retry or escalate)              +-------------------+
                                                                 | approved-for-build|
                                                                 +-------------------+
                                                                        |
                                                             Goose      | stale >24h
                                                             builds     | self-heal:
                                                                |       | toggle label
                                                                v       v
                                                         +----------------------+
                                                         | goose-implementation |
                                                         +----------------------+
                                                                |
                                                                | PR merged
                                                                v
                                                           +--------+
                                                           | merged |
                                                           +--------+
```

### Label-to-Dashboard-Column Mapping

| GitHub Label | Dashboard Column | Column Key |
|---|---|---|
| `needs-triage` | Created | `created` |
| `copilot-triaging` | Triaging | `triaging` |
| `copilot-revising` | Triaging | `triaging` |
| `spec-ready` | Spec PR | `spec` |
| `approved-for-build` | Approved | `approved` |
| `goose-implementation` | Implementing | `implementing` |
| *(PR merged)* | Merged | `merged` |

Column display order: Created, Triaging, Spec PR, Approved, Implementing, Merged.

### State Transitions

| From | To | Trigger |
|---|---|---|
| `needs-triage` | `copilot-triaging` | Copilot assigns itself to triage the issue |
| `copilot-triaging` | `copilot-revising` | Copilot revises its spec based on review feedback |
| `copilot-triaging` / `copilot-revising` | `spec-ready` | Copilot opens a spec PR |
| `spec-ready` | `approved-for-build` | Human approves the spec PR |
| `approved-for-build` | `goose-implementation` | Goose begins building the implementation |
| `goose-implementation` | *(merged)* | Implementation PR is merged |

### Self-Healing Recovery Actions

| Stale State | Threshold | Recovery Action |
|---|---|---|
| `needs-triage` | >24 hours (`createdAt`) | Remove label, wait 2s, re-apply label (re-triggers Copilot triage workflow) |
| `copilot-triaging` | >48 hours (`createdAt`) | Remove `copilot-triaging`, add `needs-triage` (resets to fresh triage) |
| `approved-for-build` | >24 hours (`updatedAt`) | Remove label, wait 2s, re-apply label (re-triggers Goose build workflow) |

Before acting, self-healing checks for an existing downstream artifact (spec PR for copilot-triaging, impl PR for approved-for-build) and skips if work is already in progress.

## Constraints and Limits

### Health Thresholds (Dashboard)

| Indicator | Time at Current Stage | Meaning |
|---|---|---|
| Green | <20 hours | Healthy, progressing normally |
| Yellow | 20--24 hours | Approaching stale threshold |
| Red | >24 hours | Stale, likely stuck |

These thresholds are defined in the dashboard frontend (`STALE_HOURS_YELLOW = 20`, `STALE_HOURS_RED = 24`).

### Stale Detection Thresholds (Self-Healing)

| Label | Stale After | Time Field Used |
|---|---|---|
| `needs-triage` | 24 hours | `createdAt` |
| `copilot-triaging` | 48 hours | `createdAt` |
| `approved-for-build` | 24 hours | `updatedAt` |

### Escalation Rules

- **Per-issue escalation:** After **2 consecutive** self-healing failures for the same issue, self-healing stops retrying and creates a `needs-human` issue with failure context.
- **Cooldown:** Once escalated, the issue enters a **24-hour cooldown** during which self-healing will not retry it.
- **Cooldown reset:** If a human closes the `needs-human` escalation issue, self-healing resumes retrying on the next cycle.
- **Counter reset:** If a human resolves the underlying issue between failure 1 and failure 2, the retry counter resets (no escalation).

### Circuit Breaker

The circuit breaker prevents cascading failures within a single self-healing run.

| Trigger | Threshold |
|---|---|
| Issues created in one run | >= 10 |
| Errors in one run | >= 5 |

When tripped:
- All remaining healing checks in the current run are **skipped**.
- A single `needs-human` escalation issue is created explaining the breach.
- The circuit breaker **resets** at the start of the next run (no persistent disabled state).

Circuit breaker checks run after each healing stage (triage, copilot, build).

### Needs-Human Auto-Close

Open `needs-human` issues are checked for resolution signals every cycle. If a signal is detected, the issue is closed automatically with a comment explaining the reason.

| Resolution Signal | Detection Method |
|---|---|
| Linked PR merged | Timeline API shows `cross-referenced` event with `merged_at` |
| API key / secret configured | Title matches `api key` or `secret`; observation loop `run_count > 0` |
| Health endpoints recovered | Title matches `health` or `endpoint`; all URLs in `health.json` return 2xx |
| Budget data populated | Title matches `burn`, `capital`, or `budget`; `costs.json` shows `available_capital > 0` |

Issues with no resolution signal are left open.

## Edge Cases

1. **Conflicting labels:** Issue has both `needs-triage` and `copilot-triaging`. Dashboard shows the more advanced stage (copilot-triaging). Self-healing evaluates each label independently per its check.

2. **Spec PR exists but copilot-triaging is stale:** Self-healing detects the open spec PR and skips recovery, treating it as work-in-progress.

3. **Impl PR exists but approved-for-build is stale:** Self-healing detects the open impl PR and skips recovery.

4. **Mass stale event (50+ issues):** Circuit breaker fires after 10 issue creates. Remaining issues are deferred to the next 2-hour cycle.

5. **GitHub API rate limit (403):** Dashboard shows cached data with a "rate limited" warning. Self-healing exits gracefully if cutoff date computation fails.

6. **Label toggle does not re-trigger workflow:** After 2 failed toggles, the issue is escalated to `needs-human`. Guard conditions in downstream workflows (e.g., `copilot-triage.yml`) prevent double-triggering.

7. **Issue closed externally during healing cycle:** Closed issues are excluded by `--state open` queries. No stale action will be attempted.

8. **Dashboard data staleness:** If cached data is >4 hours old, the dashboard displays a "Data stale. Last sync: Xh ago" warning.

## Related Documentation

| Document | Path | Purpose |
|---|---|---|
| PRD (requirements) | `.start/specs/001-pipeline-self-healing-and-observability/requirements.md` | Feature requirements and acceptance criteria |
| Self-healing workflow | `.github/workflows/pipeline-health.yml` | Implementation of all healing checks and circuit breaker |
| Dashboard frontend | `chimney/docs/pipeline.html` | Label-to-column mapping, health thresholds, Kanban rendering |
| Health state file | `company/pipeline-health-state.json` | Persistent state: retry tracker, funnel signals, run summary |
| Audit log | `company/audit-log.jsonl` | Append-only log of every self-healing action |

## Version History

| Date | Change | Author |
|---|---|---|
| 2026-03-22 | Initial version documenting pipeline state machine | -- |
