# Supervisor Clog Ranker — Requirements

**Status:** Brainstormed 2026-05-15. Awaiting plan.
**Author:** brainstorm session 2026-05-15
**Scope tier:** Deep — feature (product shape inherited from `STRATEGY.md`)

## Problem

`ai-pipeline-template` is the supervisor over the seeded-product pipeline (issue → triage → spec → impl → merge → deploy → revenue). Its job is to **unclog the pipes** without human babysitting.

Today it does not. Observed during pulse 2026-05-15:

- `company/pipeline-health-state.json` `last_check: 2026-05-10T11:51:38Z` — 5 days frozen while cron emitted 5 successful runs.
- 8 spec PRs from 2026-05-06 (`#741`–`#753`) sit unmerged 9 days. Approve/build trigger silent. No escalation surfaced.
- 5 `wgmesh` issues stuck `copilot-triaging` 7+ days (`#584`, `#573`, `#540`, `#539`, `#510`). Label never bounces.
- 6 `audit-drift` PRs (`#774`, `#866`, `#880`, `#894`, `#908`, `#922`) opened by audit cron since 2026-05-07. None reviewed or auto-closed as superseded.
- Goose autonomous-impl pipeline was silent 40 days; broke today (`#628`, `#626`) only after manual bot-guardrail fixes from operator.
- Convergence-engine output is not linked to customer-factory track: 0 cloudroof subs after CTAs live 7 days; supervisor never opened a `customer-zero-still-zero` flag.

Supervisor's failure mode is identifiable: it **monitors but does not rank, decide, or act.** Cron success is reported even when state file is untouched. There is no top-clog signal anywhere in the repo — the human is the ranker, the router, and the actor.

## Goal

Stand up a supervisor component that, on every run, produces a **ranked top-N clog list with proposed action per clog**, opens or updates a single `supervisor-rank` issue with that list, and proves it ran by mutating observable state.

Strategy-aligned: this serves **Self-heal & resilience** track in `STRATEGY.md`; its leading metric is `self_heal_resolution_rate = actions_taken / (actions_taken + needs_human_closed)`.

## Users

**Primary:** the solo founder running `ai-pipeline-template`. They open one issue (`supervisor-rank`) and see today's top clogs ranked with recommended actions, instead of running a manual pulse to discover where the pipeline is stuck.

**Secondary:** the supervisor itself (downstream) — a ranker that classifies clogs is the foundation for autonomous action wiring later. First version is read-only; the ranker output is the seed for future auto-execution.

## Value

- Eliminates the **"that you even have to ask"** failure mode: founder no longer manually inspects PR lists to find the worst clog.
- Restores trust in pipeline-health: `success` signal becomes load-bearing (state must mutate or workflow loud-fails).
- Compounds — same ranker output drives pulse, heal, and (later) auto-action wiring.

## Key Decisions

1. **Build new `supervisor-rank.yml` workflow** rather than extending `pipeline-health.yml`. Health is a per-repo doctor; rank is cross-repo + cross-stage triage. Separating concerns lets health stay narrow.
2. **Backfill `pipeline-health.yml` with state-mutation assertion** so its `success` signal stops lying. If state file is unchanged 2 consecutive runs, open `supervisor-dead` `needs-human` issue. Cheap insurance, ships in same PR or adjacent.
3. **Cross-repo scope: `ai-pipeline-template` + `atvirokodosprendimai/wgmesh`.** Other repos out of scope until customer-factory track activates a second seed.
4. **Read-only first.** No auto-actions in v1. Ranker emits ranked list + action recommendations; humans (or downstream workflow) execute. Auto-action wiring is a follow-up after 2–3 runs validate the ranks.
5. **Single tracking issue, idempotent updates.** Daily run does not spam — it edits the same `supervisor-rank` issue body. Comments only on rank change.
6. **Pipeline stage taxonomy** is a deliverable of this brainstorm:
   - `triage` — issue open without `type:*` label OR with `copilot-triaging` label
   - `spec` — open PR titled `spec:` OR `approved-for-build` label
   - `build` — `approved-for-build` issue with no impl PR opened
   - `review` — open PR with `needs-review` OR Copilot review pending
   - `merge` — open PR approved but unmerged
   - `verify` — merged impl PR awaiting e2e
   - `revenue` — seed product live, customer count below STRATEGY target
7. **Blast radius beats local dwell.** A spec PR with 3 dependent issues outranks a triage stall with 1 dependent issue, even if the triage stall is older. Ranker considers `dwell × downstream_blocked`.

## Scope

### In

- Single workflow `supervisor-rank.yml` (cron, e.g. every 4h + workflow_dispatch).
- Snapshot all PRs + issues across `atvirokodosprendimai/{ai-pipeline-template,wgmesh}`.
- Classify each into pipeline stage per taxonomy above.
- Compute `dwell_hours` per item + `downstream_blocked_count` per stage.
- Rank top 3–5 clogs by `dwell × downstream_blocked`.
- Per clog, recommend an action from a fixed set: `retry-copilot`, `bounce-label`, `auto-close-superseded`, `post-rah-bounty`, `escalate-needs-human`, `manual-merge`.
- Open or update single GitHub issue `supervisor-rank` with ranked list, dwell, and recommended action per item.
- Backfill `pipeline-health.yml` with state-mutation assertion + `supervisor-dead` loud-fail.

### Out (deferred)

- Auto-execution of recommended actions.
- Deadline-scheduler / event-driven gate refactor (Approach C). Defer until 3rd seed product onboards.
- Cross-org rollout (CloudLLM-ai/* + nycterent/*). Adds taxonomy noise; defer.
- Dashboard UI. Issue body is enough surface for v1.

### Outside this product's identity

- Replacing GitHub as orchestrator. Workflow stays in Actions cron.
- Replacing Copilot/Goose as agents. Ranker tells humans which agent failed; agents themselves are not modified here.

## Success Criteria

- v1 ships within 1 week. Single PR.
- First run produces a ranked top-3 list that the operator agrees with on visual inspection (no obviously wrong ranks).
- After 7 consecutive runs:
  - `supervisor-rank` issue body reflects current state (no stale items > 24h after they cleared).
  - `pipeline-health-state.json` `last_check` advances every run OR `supervisor-dead` issue opened.
  - Operator has acted on ≥1 ranked clog per day on average (revealed-preference signal — operator finds output useful enough to act on).
- Self-heal rate metric in pulse has a non-null source (was previously frozen).

## Dependencies / Assumptions

- GitHub Actions cron continues to fire on schedule.
- `PUSH_TOKEN` or App-token has cross-repo issue/PR read on both target repos.
- Ranker classification heuristics will mis-bucket some items — acceptable in v1, refined after 2–3 runs of operator correction.
- Operator will act on ranked output. If after 7 runs operator ignores the issue, ranker is wrong product — kill it.

## Risks

- **Mis-classification noise.** Stage taxonomy will not cover every edge case. Mitigation: emit `stage: unknown` rather than guessing; operator labels these manually for 1 week, feeding back into taxonomy.
- **Recommendation churn.** If actions recommended swing wildly run-to-run, operator loses trust. Mitigation: rank requires 2-run confirmation before flipping a stale recommendation.
- **Same anti-pattern as today.** Supervisor outputs ranked list; humans ignore it; ranker becomes another `audit-drift` pile. Mitigation: single issue (not PR); ranker comments only on rank change; auto-close when clog clears.

## Open Questions for Plan

- Token strategy: pupabobas App token (preferred per memory) or PUSH_TOKEN PAT?
- State storage: JSON file in repo (greppable, diffable) or GH workflow artifact (lighter, no commit churn)?
- Trigger cadence: every 4h matches pulse rhythm; every 1h is closer to clog detection but adds run count.
- Should the ranker write to `chimney.beerpub.dev` dashboard (HTML scrape today; could become structured) or stay purely in GH issue?

## Out-of-band notes

- Workflow naming: `.github/workflows/supervisor-rank.yml`.
- Tracking issue: `supervisor-rank` (singular, idempotent).
- Stage taxonomy lives in `company/pipeline-stages.json` (canonical) — referenced by both ranker and any future event-driven gate.
- Cross-link to existing memory: ranker classification will catch `copilot-triaging` stalls noted in `feedback_workflow_path_race.md` and `feedback_bot_merge_trigger_gap_synchronize.md` patterns.

## Next step

Hand to `ce-plan` for implementation breakdown.
