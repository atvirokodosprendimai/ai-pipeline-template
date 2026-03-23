---
tldr: Broad drift report — all 7 specs checked against implementation code
category: core
---

# Drift: Full spec graph vs codebase

## Claim Verification

### Observation Loop

- [x] 8-hour cadence (00:00, 08:00, 16:00 UTC) — upheld (`cron: '0 0,8,16 * * *'`)
- [x] `repository_dispatch` type `company-signal` — upheld
- [x] Primary/secondary repo collection split — upheld
- [x] Sanitise before commit — upheld (multiple `sanitise.sh` call sites)
- [x] Fail-safe stub on LLM failure — upheld
- [x] Concurrency group `observation-loop` with `cancel-in-progress: false` — upheld
- [x] Fuzzy dedup with keyword matching — upheld
- [x] Three archival destinations (loop-history, loop-state, episodic) — upheld
- [x] Stale needs-triage re-trigger at end of run — upheld

### Pipeline State Machine

- [x] Entry labels: `needs-triage`, `fn:dev`, `bug` — upheld in `copilot-triage.yml`
- [x] Guard condition: skip if `copilot-triaging` present — upheld
- [x] Spec file at `specs/issue-{N}-spec.md` — upheld
- [x] PR title pattern `spec: Issue #{N}` — upheld
- [x] Draft auto-promotion for Copilot PRs — upheld in `copilot-undraft.yml`
- [x] Deterministic validation via `validate-spec.sh` — upheld
- [ ] **Spec claims `spec-ready` label is part of the flow** — DIVERGES: `spec-validation.yml` applies `approved-for-build` directly on pass, skipping `spec-ready`. The `spec-ready` label exists in `labels.yml` but no workflow consumes it. The domain doc (`pipeline-state-machine.md`) lists it as a state, but the code bypasses it.
- [x] `spec-needs-fix` on validation failure — upheld
- [x] Implementation merge closes originating issue — upheld in `impl-merged-close.yml`
- [x] Exclusion labels (`wont-do`, `needs-info`, `manual-only`) — upheld
- [ ] **Spec says `goose-implementation` label is part of the flow** — UNCERTAIN: the label exists in `labels.yml` but `goose-build.yml` is in `workflow-templates/` (not active). The actual build uses `building` label via `spec-merged-build.yml`. The Goose build template may be activated per-fork.

### Self-Healing

- [x] 2-hour cron (`0 */2 * * *`) — upheld
- [x] Three monitored stages with distinct thresholds — upheld
- [x] Label toggle recovery for `needs-triage` and `approved-for-build` — upheld
- [x] State reset to `needs-triage` for `copilot-triaging` — upheld
- [x] Exclusion labels checked — upheld
- [x] In-progress artifact guard (spec PR / impl PR check) — upheld
- [x] Per-issue escalation after 2 consecutive failures — upheld
- [x] Circuit breaker (10 creates / 5 errors) — upheld
- [x] Needs-human auto-close with 4 resolution signals — upheld
- [x] Audit trail to `audit-log.jsonl` — upheld
- [x] State file segregation (`pipeline-health-state.json` only) — upheld
- [x] Funnel signals (dogfood, presence) — upheld

### PR Review and Merge

- [x] Author allowlist as first check — upheld (`APPROVED_AUTHORS` env)
- [x] Script runs from `main` — upheld (`ref: main` in workflow)
- [x] Copilot review polling — upheld
- [x] Fix loop with retry counter — upheld
- [x] Manual push detection resets counter — upheld
- [x] `manual-only` label immediate exit — upheld
- [x] Five guardrails in cheapest-first order — upheld
- [x] Protected paths (empty default) — upheld after coherence fix
- [x] Size limit (`PR_MAX_LINES` default 500) — upheld
- [x] Security keyword scan on additions only — upheld
- [x] Squash merge with `--admin --delete-branch` — upheld
- [x] Circuit breaker at 5 errors — upheld
- [x] Sanitise all published content — upheld

### Infrastructure Monitoring

- [x] 15-minute cron cadence — upheld (`*/15 * * * *`)
- [x] Three endpoint states: `up`, `unreachable`, `error:<code>` — upheld
- [x] Issue creation with `health-check` + `needs-human` labels — upheld
- [x] Duplicate suppression via label query — upheld
- [x] Auto-close on recovery — upheld
- [x] Sparse checkout — upheld
- [x] Latency measurement via `date +%s%N` — upheld

### Security and Quality Framework

- [x] Andon principle codified — upheld (CONSTITUTION.md §Foundational)
- [x] SEC-1 through SEC-7 — upheld (all patterns verifiable in code)
- [x] QUAL-1 (`set -euo pipefail`) in all scripts — upheld
- [x] QUAL-2 (atomic jq writes) — upheld
- [x] QUAL-4 (conventional commits) — upheld in git history
- [x] `sanitise.sh` stdin/stdout contract — upheld
- [x] Amendment process with evidence requirement — upheld

### Testing Infrastructure

- [x] PASS/FAIL counters in all test scripts — upheld
- [x] `trap cleanup EXIT` — upheld
- [x] Pre-flight validation — upheld
- [x] Cutoff override via `workflow_dispatch` input — upheld
- [x] Mock `gh` shim pattern — upheld in `test-pr-review-merge.sh`
- [x] Function extraction via `awk`/`eval` — upheld in `test-pr-review-merge.sh`

## Orphaned Mappings

None found (script confirmed).

## Code Exceeding Spec

### E1 — `spec-ready` label defined but unused

`labels.yml:17` defines `spec-ready`. The pipeline state machine domain doc references it. But the actual workflow (`spec-validation.yml`) jumps from validation directly to `approved-for-build`. The `spec-ready` label appears to be vestigial — either it was part of an earlier design where human approval happened on the `spec-ready` state, or it's intended for future use.

### E2 — `goose-implementation` label vs `building` label

`labels.yml:29` defines `goose-implementation`. `spec-merged-build.yml:56` applies `building`. The dashboard domain doc maps `goose-implementation` to the "Implementing" column. These may be the same intent under different names, or `goose-implementation` may be applied by the Goose build workflow template when activated.

### E3 — `goose-build.yml` is a workflow template, not active

`goose-build.yml` lives in `.github/workflow-templates/`, not `.github/workflows/`. It's a template that forks activate. The pipeline state machine spec doesn't distinguish between template (dormant) and active workflows. The actual build trigger is `spec-merged-build.yml` which assigns Copilot, not Goose.

### E4 — `copilot-revising` label in triage workflow

The pipeline SM spec mentions `copilot-revising` for the revision cycle, but the label is applied by the approve-build workflow (`approve-build.yml`), not by the triage workflow. The triage flow is: `needs-triage` → `copilot-triaging` → (spec PR opens). Revision is triggered by a human requesting changes on the spec PR review.

## Future Items Already Implemented

None found (script confirmed).

## Suggested Actions

1. **Decision needed:** Resolve `spec-ready` vs `approved-for-build` flow. Is `spec-ready` vestigial or intended for a future human-review gate between validation and build trigger? If vestigial, remove from `labels.yml` and update domain doc.
   **Resolved:** `spec-ready` is vestigial — auto-validation skips it. Spec updated to note it exists but is unused by automated flow. Label kept in `labels.yml` for potential manual use.

2. **Decision needed:** Resolve `goose-implementation` vs `building` label. Are these the same stage? Should one be removed? The dashboard expects `goose-implementation`; the code applies `building`.
   **Resolved:** Code bug — `spec-merged-build.yml` was applying `building` instead of `goose-implementation`. Fixed to use `goose-implementation` to match `labels.yml` and dashboard.

3. **Pull/update:** The pipeline state machine spec should clarify the workflow-templates vs active workflows distinction. `goose-build.yml` is a template for forks, not an active workflow in this repo.
   **Resolved:** Pipeline SM spec updated with "Active workflows vs templates" design note.

## Summary

- **Drift level: Low**
- 50+ claims verified, 2 divergent (both label-naming discrepancies)
- 0 orphaned mappings
- 4 code patterns exceeding spec (all related to label naming / workflow template confusion)
- No fundamental intent-vs-reality gaps
