---
tldr: Deterministic (no LLM) recovery of stale pipeline issues via label toggles, with per-issue escalation, circuit breaker, and needs-human auto-close.
category: core
---

# Self-Healing

## Target

Ensure every issue progresses through the autonomous pipeline without human intervention. When an issue stalls at a pipeline stage past its stale threshold, the system re-triggers the responsible workflow automatically. When deterministic recovery fails repeatedly, it surfaces the problem to a human. When the human-visible problem resolves, it closes its own escalation ticket.

## Behaviour

- The self-healing check runs on a fixed 2-hour cron (`0 */2 * * *`) and can be triggered manually via `workflow_dispatch`. {>> concurrency group `pipeline-health` with `cancel-in-progress: false` ensures runs queue rather than collide}
- Three pipeline stages are monitored for staleness, each with a distinct threshold and time field:
  - `needs-triage` stale after **24 hours** measured from `createdAt`
  - `copilot-triaging` stale after **48 hours** measured from `createdAt`
  - `approved-for-build` stale after **24 hours** measured from `updatedAt`
- Recovery for `needs-triage` and `approved-for-build` is a **label toggle**: remove the label, wait 2 seconds, re-apply it. This re-fires the watching GitHub workflow without any code changes. {>> the 2-second sleep is required for GitHub's event system to treat the re-apply as a distinct event}
- Recovery for `copilot-triaging` is a **state reset**: remove `copilot-triaging`, apply `needs-triage`. This discards partial triage work and starts fresh rather than re-poking a potentially broken Copilot session.
- Issues carrying any exclusion label (`manual-only`, `wont-do`, `needs-info`) are **skipped entirely** and never touched, regardless of age.
- Before acting on a stale `copilot-triaging` issue, the system checks for an open spec PR matching `spec: Issue #N`. If found, work is in progress and recovery is skipped.
- Before acting on a stale `approved-for-build` PR, the system checks for an open impl PR matching `impl: Issue #N`. If found, recovery is skipped.
- **Per-issue escalation**: if self-healing has attempted recovery for the same issue **2 consecutive times** without success, it creates a `needs-human` issue with failure context and stops retrying. {>> retry count is stored in `retry_tracker[issue_number]` inside `pipeline-health-state.json`}
- After escalation, the issue enters a **24-hour cooldown**. Self-healing will not attempt recovery again until the cooldown expires.
- If a human resolves the underlying issue between the first and second retry, the retry counter resets on the next cycle and escalation never fires.
- **Circuit breaker**: within a single run, if `ISSUES_CREATED >= 10` OR `ERRORS >= 5`, all remaining healing steps are skipped and a single `needs-human` issue is created explaining the breach. The circuit breaker resets at the start of the next run — there is no persistent disabled state. {>> checked after each of the three healing stages (triage, copilot, build)}
- **Needs-human auto-close**: every run scans open `needs-human` issues for resolution signals and closes them automatically with a comment explaining the resolution. Issues with no signal are left open.
  - Resolution signal 1: timeline API shows a cross-referenced event where the linked PR has `merged_at` set.
  - Resolution signal 2: title contains `api key` or `secret` and observation loop `run_count > 0`.
  - Resolution signal 3: title contains `health` or `endpoint` and all URLs in `health.json` return 2xx.
  - Resolution signal 4: title contains `burn`, `capital`, or `budget` and `costs.json` shows `available_capital > 0`.
- Needs-human issues with `manual-only` are excluded from auto-close.
- **Audit trail**: every action (label toggle, escalation, circuit breaker trip, needs-human close, funnel signal check) is appended as a JSON line to `company/audit-log.jsonl` with `timestamp`, `run_id`, `action`, `issue_number`, `target_repo`, `reason`, `outcome`, and `retry_count`.
- State is persisted to `company/pipeline-health-state.json` after each run, including cumulative `checks_run`, `issues_healed_total`, per-run summary counts, the retry tracker, and funnel signals. This file is committed back to the repository via a branch PR. {>> the workflow never writes to `company/loop-state.json`, which is owned by the observation loop}
- **Funnel signals** are checked each run: `dogfood` (wgmesh CLAUDE.md contains Architecture and Build sections) and `presence` (all configured health endpoints return 2xx). Signal results are stored in `pipeline-health-state.json` under `funnel_signals` and are available to the dashboard.
- All issue/comment bodies pass through `company/scripts/sanitise.sh` before being submitted to the GitHub API. If sanitisation fails, the action is skipped and counted as an error.
- Closed issues are excluded from all stale checks via `--state open` filtering; a closed issue will never receive a healing action.
- If the date computation for a cutoff fails (e.g., on an unsupported platform), the affected sweep is skipped with a warning rather than acting on incorrect data.

## Design

**Deterministic-only recovery.** No LLM calls, no heuristics beyond time thresholds and title keyword matching. Every decision is reproducible given the same state file and GitHub API responses. This makes failures diagnosable from logs alone.

**Label-as-event-trigger.** GitHub workflow `on: issues: types: [labeled]` triggers re-execute when a label is re-applied. The 2-second wait is the minimal gap for GitHub to register the re-apply as a new event. This keeps recovery decoupled from the health workflow itself — self-healing does not call downstream workflows directly.

**Stage-specific recovery strategy.** `needs-triage` and `approved-for-build` toggle in place because the responsible downstream workflow is stateless and idempotent on re-trigger. `copilot-triaging` resets to `needs-triage` because Copilot may have entered a broken session state; a full reset is safer than a re-poke.

**Per-issue retry state, not per-run.** The retry tracker is keyed by issue number (and `pr-N` for PRs) and persisted between runs. This allows the system to accumulate failure evidence across the 2-hour cycle boundary before escalating.

**Two-tier safety.** Per-issue escalation (2 failures → needs-human) protects against a single broken issue consuming unlimited healing cycles. The circuit breaker (10 creates / 5 errors per run) protects against mass failure events (e.g., GitHub API instability or 50+ issues going stale simultaneously) consuming the entire run budget.

**Self-closing escalations.** needs-human issues are not permanent. The system monitors them and closes them when observable signals indicate resolution. This prevents escalation accumulation and keeps the human-visible signal meaningful — an open `needs-human` issue means the problem is genuinely unresolved.

**State file segregation.** `pipeline-health-state.json` is owned exclusively by this workflow. `loop-state.json` is owned exclusively by the observation loop. Cross-reading is permitted (needs-human auto-close reads `loop-state.json` to detect observation loop health), but cross-writing is forbidden.

**E2E testability via override.** The `cutoff_override_minutes` input allows tests to artificially age issues without waiting 24–48 hours, making end-to-end testing of the full healing path practical.

## Interactions

- Depends on [[spec - pipeline state machine - label driven issue lifecycle]] for the canonical label definitions, stale thresholds, and exclusion label semantics.
- Label toggle recovery directly re-triggers the Copilot triage workflow (`copilot-triage.yml`) and the Goose build workflow. Guard conditions in those workflows prevent double-triggering on duplicate label events.
- State commits (branch + PR) flow through [[spec - pr review merge - autonomous bot pr guardrails]] — the `bot-pr-review-merge.yml` workflow auto-merges heal PRs.
- Issue and comment content passes through the sanitisation script before any GitHub API write; this is the boundary enforced by [[spec - security quality - constitution and enforcement]].
- Reads `company/loop-state.json` (observation loop state) as a resolution signal for api-key/secret needs-human issues, but never writes to it.
- Reads `company/health.json` for endpoint URLs used in both presence signal checking and health-related needs-human auto-close.
- Reads `company/costs.json` for budget resolution signal detection.
- Funnel signals (`dogfood`, `presence`) are written to `pipeline-health-state.json` and consumed by the Chimney dashboard pipeline view.

## Mapping

> - [[.github/workflows/pipeline-health.yml]] — full self-healing implementation: stale checks, circuit breaker, needs-human auto-close, funnel signals, state commit
> - [[company/pipeline-health-state.json]] — persistent state: retry tracker, funnel signals, run summary, cumulative counters
> - [[docs/domain/pipeline-state-machine.md]] — canonical state machine: label definitions, stale thresholds, exclusion labels, escalation rules, edge cases
> - [[company/audit-log.jsonl]] — append-only audit trail written by every self-healing action
