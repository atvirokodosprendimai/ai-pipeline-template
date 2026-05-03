---
title: "feat: monthly STRATEGY.md drift audit with auto-PR on threshold breach"
type: feat
status: active
date: 2026-05-03
---

# feat: monthly STRATEGY.md drift audit with auto-PR on threshold breach

## Summary

Add a recurring monthly GitHub Actions workflow (`strategy-audit.yml`) that re-evaluates the 5 metrics declared in `STRATEGY.md` against realized values from the local pipeline-health state file, GitHub PR data, and the public chimney dashboard. When measured drift exceeds configured thresholds (>25% delta vs baseline, or a passed-but-unmet milestone date), the workflow opens a PR titled `audit: strategy drift detected YYYY-MM` proposing concrete edits to `STRATEGY.md` with evidence. Uses the org-installed `pupabobas` GitHub App for PR creation (no PAT-as-author email noise) and is fully idempotent (same calendar month → no duplicate PR).

---

## Problem Frame

`STRATEGY.md` was just authored 2026-05-03 and names 5 metrics + 5 dated milestones. Without a closed-loop audit, the document drifts from reality silently — milestones slip, metrics regress, and the founder keeps reading aspirational numbers while the dashboard tells a different story. The strategy doc becomes a stale artifact instead of a live anchor for `ce-ideate` / `ce-brainstorm` / `ce-plan` grounding (which all consume it).

Manual monthly review works for one founder, one product. The point of `ai-pipeline-template` is to remove that babysitting cycle. Drift detection should be machine-enforced, not memory-enforced.

---

## Requirements

- R1. Workflow runs on `cron: '0 9 1-7 * 1'` (first Monday of each month, 09:00 UTC) plus `workflow_dispatch` for ad-hoc audits.
- R2. Workflow skips cleanly with a `::notice::` (not failure) when `STRATEGY.md` is missing or has no `last_updated` frontmatter.
- R3. Five metric values are computed each run and persisted to `company/strategy-audit-baseline.json` (one entry per audit run, history preserved).
- R4. Drift triggers per-metric: delta vs previous baseline > 25% in unfavorable direction (e.g., self-heal rate dropped >25%, lead time grew >25%, stuck issues grew >25%, autonomous-ship rate dropped >25%, paid customers dropped >25%). Paid customers behaves asymmetrically — drop is drift; growth is not.
- R5. Milestone drift triggers when a `STRATEGY.md` milestone date has passed and the implied target metric is not met (e.g., milestone `2026-08-01 — 1 paying customer` and current paid customers count is 0 on or after that date).
- R6. On any drift trigger, workflow opens a PR titled `audit: strategy drift detected YYYY-MM` whose body lists each metric (baseline, current, delta, drift verdict), the milestone status, and a suggested STRATEGY.md edit (e.g., "consider revising the Y2 customer target from 42 to ___"). Suggested edits are advisory text in the PR body, NOT auto-applied to `STRATEGY.md`.
- R7. Idempotency: if a PR with the title pattern `audit: strategy drift detected YYYY-MM` for the current YYYY-MM already exists (open or merged), workflow updates that PR's body in place rather than opening a duplicate.
- R8. Workflow uses `actions/create-github-app-token@v2` with `vars.APP_ID` + `secrets.APP_PRIVATE_KEY` (org-level, visibility ALL) for PR creation — same pattern as `pipeline-health.yml` post-PR-#675. No `secrets.PUSH_TOKEN` for PR creation steps.
- R9. The PR's author is `pupabobas[bot]`, which `bot-pr-review-merge.yml` filter (line 23, post-#675) already accepts → auto-merge fires if PR is clean.
- R10. Workflow appends a typed thought to MentisDB on completion per the canonical pattern (`thought_type: Insight` on success+no-drift, `thought_type: Mistake` on drift detected, `thought_type: Mistake` on workflow failure). Non-fatal append.
- R11. No new repo secrets introduced. Reuses org-inherited `APP_PRIVATE_KEY`, `MENTISDB_*`, plus repo-existing `PUSH_TOKEN` for cross-repo wgmesh API calls if needed.
- R12. All sanitisation goes through `company/scripts/sanitise.sh` before commit (per project convention).

---

## Scope Boundaries

- Not auto-editing `STRATEGY.md` content. Edits are advisory in PR body; the founder applies them via review.
- Not collapsing `pipeline-health.yml` into this workflow. They run on different cadences (2h vs monthly) and own different concerns (operational healing vs strategic drift).
- Not measuring product-side metrics from beyond chimney + this repo. cloudroof.eu KPIs (if any not on chimney) are out of scope; chimney is the canonical surface per STRATEGY.md.
- Not introducing Polar/Stripe API client. Paid customers count is read off the chimney HTML (already proven via WebFetch in the strategy interview) — direct API integration is a deferred follow-up if HTML scraping proves brittle.
- Not changing the metric definitions in `STRATEGY.md`. Drift detection consumes the doc; it does not redesign the metric set.
- Not introducing dashboards or Grafana. Baseline JSON + PR audit trail is the persistence layer.

### Deferred to Follow-Up Work

- Polar/Stripe direct API integration for paid-customer count (if chimney HTML proves brittle): separate plan.
- Per-metric configurable threshold (currently hardcoded 25%): separate config schema if multiple users adopt the audit pattern.
- Cross-repo strategy audit (multiple seeded products): separate plan once a 2nd seed exists.

---

## Context & Research

### Relevant Code and Patterns

- `.github/workflows/pipeline-health.yml` — reference for: `actions/create-github-app-token@v2` step, `gh pr create` with App token, sanitise + commit + PR pattern, MentisDB append step, retry/cooldown JSON state pattern, circuit breaker structure.
- `.github/workflows/bot-pr-review-merge.yml` — confirms `pupabobas[bot]` filter is in place (post-PR-#675).
- `STRATEGY.md` — source of truth: 5 metrics with sources, 5 dated milestones, "Not working on" rule.
- `company/pipeline-health-state.json` — provides `actions_taken`, `errors`, `needs_human_closed`, `stale_*_found`, `last_run_summary` fields needed for self-heal rate + active stuck issues.
- `company/audit-log.jsonl` — append target for the new workflow's audit events (mirrors pipeline-health.yml convention).
- `company/scripts/sanitise.sh` — required step before any commit.
- `https://chimney.beerpub.dev/` — public surface for paid customers count (HTML scrape via curl + grep/jq, no auth).

### Institutional Learnings

- `memory/reference_pupabobas_app.md` — App credentials available org-wide as of 2026-05-02; bot login is `pupabobas[bot]`.
- `memory/feedback_pat_pr_email_spam.md` — PAT-authored automated PRs spam user via auto-subscribe; App token avoids it.
- `memory/reference_mentisdb_ci_integration_pattern.md` — canonical workflow→thought append pattern, fatality table, chain naming convention.
- `memory/feedback_workflow_path_race.md` — push-trigger workflows with overlapping path filters race; this workflow uses `pull_request` trigger? No — `schedule` + `workflow_dispatch` only, no path filter, no race.
- `memory/feedback_check_git_index_before_commit.md` — use scoped `git commit -- <paths>`; never bare `git add -A` in workflow.

### External References

- None needed. All patterns and primitives are local.

---

## Key Technical Decisions

- **Compute metrics in inline bash + jq, not a separate script.** Rationale: matches pipeline-health.yml convention, avoids new file in `company/scripts/` until the logic stabilizes. If logic grows past ~150 lines, extract to `company/scripts/strategy-audit.sh` in a follow-up.
- **Drift threshold = 25% hardcoded.** Rationale: simplest possible threshold, easy to tune later. Bake the literal `25` as a workflow env var so a single-line change adjusts it without redeploying logic.
- **Idempotency via PR title search, not a state file.** Rationale: source of truth is the PR list itself. `gh pr list --search "audit: strategy drift detected $(date -u +%Y-%m)" --json number,state` → if any returns, edit body in place; else create new. State file would drift from PR reality.
- **Baseline file is append-only history, not single-row state.** Rationale: lets future audits compute trends, not just last-vs-current. Schema: `{audits: [{ran_at, metrics: {...}, milestones_status: {...}}]}`. Cap at last 24 entries (2 years monthly).
- **Suggested edits in PR body are templated, not LLM-generated.** Rationale: keeps the workflow deterministic, no new API key needed, avoids review-fatigue from LLM hallucination on numeric targets. Templates: "Y2 customer target (42) appears unreachable at current pace — consider revising or reaffirming." Founder applies the actual edit during PR review.
- **Paid customers asymmetric threshold.** Drop ≥25% triggers drift; growth never does. Rationale: a customer LEAVING is signal; gaining customers is the goal, not drift.
- **No path filter, no concurrency group.** Rationale: monthly cron, no race window. Adding `concurrency: strategy-audit` would block manual `workflow_dispatch` smoketests after a scheduled run on the same day. Idempotency at the PR layer (R7) handles double-fire.
- **Use `pupabobas[bot]` for both branch push AND PR creation.** Same as PR #675 pattern. Avoids any user PAT identity on the audit PR.

---

## Open Questions

### Resolved During Planning

- **Where does paid customers live?** Polar/Stripe direct API would be authoritative but requires new secret. Chimney already publishes the value via dashboard ("Paid subscribers: 0"). Resolution: scrape chimney HTML for now; deferred Polar API integration if scrape proves brittle.
- **What if a metric source returns nothing (e.g. chimney HTML unreachable)?** Resolution: workflow records `metric_value: null, fetch_status: "fetch_failed"` in baseline, does NOT count as drift, emits `::warning::`. Three consecutive null reads escalate to a `[needs-human]` issue (parallel to pipeline-health.yml escalation logic) — but that escalation is a follow-up; v1 just warns.
- **Workflow trigger time.** First Monday of month at 09:00 UTC = `0 9 1-7 * 1` (cron firing on Mon if day-of-month is 1-7). Resolved.
- **Should drift PR include milestone delta dates?** Yes. PR body has a "Milestone status" section listing each STRATEGY.md milestone with: target date, target value, current value, status (met / pending / overdue).
- **Where does the suggested-edit text live?** Hardcoded templates in the workflow's bash. One template per metric category, parameterized with current/baseline numbers.

### Deferred to Implementation

- Exact `gh` query syntax for "median lead time spec→merge over last 30 days" — depends on how PRs are labeled and filtered. The implementer will write the actual gh search/jq pipeline against real data.
- Exact HTML extraction selectors for chimney "Paid subscribers" — current chimney HTML structure may shift; implementer reads the current rendered HTML and picks robust grep/jq patterns.
- Chimney HTML scrape robustness — first cron run will reveal whether the chosen pattern survives chimney updates. Deferred fix-on-failure.

---

## Implementation Units

- U1. **Baseline file schema + reader/writer**

**Goal:** Establish the on-disk shape of `company/strategy-audit-baseline.json` and the jq read/write helpers used by U2-U5.

**Requirements:** R3, R4

**Dependencies:** None

**Files:**
- Create: `company/strategy-audit-baseline.json` (initial empty `{"audits": []}`)
- Test: none — pure data file; logic lives in U2-U5 and is tested via workflow smoketest in U6

**Approach:**
- Schema: `{"audits": [{"ran_at": ISO8601, "metrics": {paid_customers, autonomous_ship_rate, lead_time_hours, self_heal_rate, active_stuck_issues}, "milestones_status": [{date, target, current, status}]}]}`.
- Cap at last 24 entries (slice in workflow's append step).
- Initial commit ships an empty `audits: []` so the first cron run has somewhere to write.

**Patterns to follow:**
- `company/pipeline-health-state.json` for similar JSON-state convention (jq update, mv-and-rename).

**Test scenarios:**
- Test expectation: none — pure scaffolding file. Validation happens in U6 smoketest.

**Verification:**
- File exists with valid JSON, empty `audits` array.

---

- U2. **Workflow skeleton: trigger, App token, checkout, skip-guard, MentisDB append**

**Goal:** Stand up the bones of `.github/workflows/strategy-audit.yml` — cron + dispatch trigger, App token step, checkout, skip-when-no-STRATEGY guard, MentisDB tail append. No metric logic yet; subsequent units fill it in.

**Requirements:** R1, R2, R8, R10, R11

**Dependencies:** U1 (baseline file must exist for downstream units)

**Files:**
- Create: `.github/workflows/strategy-audit.yml`

**Approach:**
- `on: schedule: - cron: '0 9 1-7 * 1'` + `workflow_dispatch:`
- `permissions:` block matches `pipeline-health.yml` (`contents: write`, `pull-requests: write`, `actions: read`).
- Steps in order: Generate App token → Checkout (`token: ${{ steps.app-token.outputs.token }}`) → Skip-guard (test for `STRATEGY.md` + `last_updated:` frontmatter; `exit 0` with `::notice::` if missing) → placeholder for U3-U5 metric steps → placeholder for U6 drift+PR step → MentisDB append (`if: always()`, non-fatal `||` per fatality table).
- Skip-guard logic: `grep -q '^last_updated:' STRATEGY.md || { echo "::notice::no last_updated"; exit 0; }`.

**Patterns to follow:**
- `.github/workflows/pipeline-health.yml` lines 31-42 (App token + checkout pattern, post-#675).
- `.github/workflows/pipeline-health.yml` lines 819-857 (MentisDB append step).

**Test scenarios:**
- Happy path: rename `STRATEGY.md` away → `workflow_dispatch` run → workflow exits with `::notice::` and zero failures.
- Happy path: rename back → `workflow_dispatch` run → workflow runs full sequence (verified after U3-U6 land).

**Verification:**
- `gh workflow run strategy-audit.yml` succeeds with skip-notice when STRATEGY absent.
- App token step succeeds with org-level vars/secrets (no manual repo override).
- MentisDB thought lands in `chain_key=ai-pipeline-template`.

---

- U3. **Metric computation: self-heal rate + active stuck issues (local sources)**

**Goal:** Compute the 2 metrics that source from `company/pipeline-health-state.json` + `gh issue list` — fastest, no external HTTP.

**Requirements:** R3

**Dependencies:** U2

**Files:**
- Modify: `.github/workflows/strategy-audit.yml`

**Approach:**
- Self-heal rate: `jq '.last_run_summary | (.actions_taken / (.actions_taken + .needs_human_closed + 0.0001))' company/pipeline-health-state.json` (epsilon avoids div-by-zero).
- Active stuck issues: `gh issue list --repo "$TARGET_REPO" --state open --label needs-human --json number | jq 'length'` PLUS issues currently in retry cooldown (parsed from `state_file.retry_tracker[*].cooldown_until` where cooldown_until > now).
- Write computed values into `$GITHUB_ENV` for later assembly.

**Patterns to follow:**
- `.github/workflows/pipeline-health.yml` lines 591-666 (cooldown parsing pattern).

**Test scenarios:**
- Happy path: with current pipeline-health-state.json (actions_taken=N, needs_human_closed=M), computed rate matches manual N/(N+M) calculation to 4 decimal places.
- Edge case: `actions_taken = 0, needs_human_closed = 0` → rate = 0 (not NaN).
- Edge case: no `needs-human` open issues + no active cooldowns → stuck issues = 0.

**Verification:**
- After U6 lands, run `workflow_dispatch` → baseline file appended with non-null `self_heal_rate` and `active_stuck_issues`.

---

- U4. **Metric computation: lead time + autonomous-ship rate (gh PR data)**

**Goal:** Compute the 2 metrics derived from GitHub PR/issue history.

**Requirements:** R3

**Dependencies:** U2

**Files:**
- Modify: `.github/workflows/strategy-audit.yml`

**Approach:**
- Lead time: list issues that were ever labeled `needs-triage` and have a linked merged PR within the last 30 days. For each, compute hours from `needs-triage` first applied → linked PR merged. Median in jq.
- Autonomous-ship rate: of merged PRs in last 30 days authored by `goose[bot]` or `copilot-swe-agent[bot]` (bot list per `bot-pr-review-merge.yml` filter), count those that merged with zero non-bot review comments / zero `needs-human` escalations attached. Numerator = autonomous-merged. Denominator = total bot-authored merged PRs.
- Both pull from `gh issue list --search 'is:closed label:needs-triage'` + `gh pr list --search 'is:merged ...'` over a 30-day window (`--search "merged:>=$(date -u -d '30 days ago' +%Y-%m-%d)"` with macOS fallback).
- Note: The `gh pr` queries here read from `$TARGET_REPO` env var pointing to `atvirokodosprendimai/wgmesh` (where the seeded products actually live). For `ai-pipeline-template`'s own meta-pipeline metrics, point at `${{ github.repository }}` instead. Decision: this audit measures the SEEDED product's pipeline (wgmesh), since that's what the strategy is about converging. Use `wgmesh` as TARGET_REPO. Make this an input to `workflow_dispatch` for ad-hoc re-audits of other seeds later.

**Execution note:** `gh search` query syntax is the highest-risk part of this unit. Implementer should iterate against real data, then commit. Expect 1-2 query refinements before numbers settle.

**Patterns to follow:**
- `.github/workflows/pipeline-health.yml` lines 92-97 (cross-repo gh issue list with cutoff).

**Test scenarios:**
- Happy path: at least 1 merged bot-authored PR exists in last 30d → autonomous-ship rate computes to a value in [0, 1].
- Edge case: zero merged PRs in last 30d → both metrics record `null`, fetch_status `"no_data"`, NOT counted as drift.
- Edge case: a PR labeled `needs-triage` that was closed without merge → excluded from lead-time calc.

**Verification:**
- After U6 lands, baseline `metrics.lead_time_hours` and `metrics.autonomous_ship_rate` are populated for at least one historical month.

---

- U5. **Metric computation: paid customers (chimney HTML scrape)**

**Goal:** Read paid-customers count from `https://chimney.beerpub.dev/` HTML.

**Requirements:** R3

**Dependencies:** U2

**Files:**
- Modify: `.github/workflows/strategy-audit.yml`

**Approach:**
- `curl --fail-with-body --silent --max-time 15 https://chimney.beerpub.dev/ -o /tmp/chimney.html` then grep/sed for the "Paid subscribers" line. Implementer picks robust pattern by inspecting current rendered HTML.
- If curl fails or grep returns no match: write `metrics.paid_customers: null, fetch_status: "fetch_failed"` and emit `::warning::`. Do NOT count as drift.
- Cache hit-rate / API-remaining displayed on chimney are NOT collected — out of scope.

**Execution note:** HTML structure is owned by another workflow. First-run brittleness expected. Pattern fix iterates on chimney updates.

**Patterns to follow:**
- `.github/workflows/pipeline-health.yml` lines 531-549 (curl with timeout + status check).

**Test scenarios:**
- Happy path: chimney reachable, "Paid subscribers" extractable → integer >=0 lands in baseline.
- Error path: curl times out → `null` recorded, workflow continues (does NOT fail).
- Edge case: HTML present but selector pattern misses the value → `null` recorded with `::warning::`, workflow continues.

**Verification:**
- After U6 lands, baseline `metrics.paid_customers` populated on first successful run.

---

- U6. **Drift detection + idempotent PR creation**

**Goal:** Compare current metric values against last baseline entry, evaluate milestone status, build PR body, open OR update PR depending on idempotency check.

**Requirements:** R4, R5, R6, R7, R9, R12

**Dependencies:** U3, U4, U5

**Files:**
- Modify: `.github/workflows/strategy-audit.yml`
- Create: none beyond the workflow

**Approach:**
- Read previous baseline entry (last item in `audits` array). If empty → first run, no drift possible, append baseline only, exit success with `::notice::`.
- For each metric, compute delta vs previous: `(current - prev) / max(abs(prev), 0.0001)`. Compare against threshold env var `DRIFT_THRESHOLD=0.25`. Direction-aware: paid_customers/autonomous_ship_rate/self_heal_rate trigger on drop ≥25%; lead_time_hours/active_stuck_issues trigger on growth ≥25%.
- Milestone status: parse `STRATEGY.md` `## Milestones` section with awk/sed. For each milestone with date < today, compare current metric vs target → status `met`/`overdue`.
- Append new entry to `company/strategy-audit-baseline.json`, slice to last 24, sanitise via `company/scripts/sanitise.sh`, commit.
- If ANY drift trigger fires OR any milestone is overdue: build PR body markdown with sections "Metric drift", "Milestone status", "Suggested edits" (per-metric template strings).
- Idempotency: `month=$(date -u +%Y-%m); existing=$(gh pr list --search "audit: strategy drift detected $month in:title" --state all --json number --jq '.[0].number // empty')`. If `existing` set → `gh pr edit $existing --body-file /tmp/audit-body.md`. Else create new branch `audit/strategy-drift-$month`, push via App token, `gh pr create`.
- If no drift AND no milestone overdue: just commit baseline update on a branch, open low-priority PR? OR commit directly? Decision: commit baseline-only update via PR titled `audit: strategy baseline $month` (separate title pattern from drift PR), so `bot-pr-review-merge.yml` can auto-merge the no-drift baseline updates without human review and the drift PR title pattern stays reserved for actual drift.

**Patterns to follow:**
- `.github/workflows/pipeline-health.yml` lines 793-816 (commit + branch + `gh pr create` via App token).
- Memory `feedback_check_secrets_before_set.md` — App token already verified org-level on 2026-05-02.
- Memory `feedback_check_git_index_before_commit.md` — use `git commit -- company/strategy-audit-baseline.json` (scoped path) to avoid pulling unrelated working-tree changes.

**Test scenarios:**
- Happy path: first run (baseline empty) → baseline appended, no PR created, workflow exits clean.
- Happy path: second run with no metric changes → baseline appended, baseline-only PR opened (`audit: strategy baseline YYYY-MM`), auto-merges.
- Drift path: lead_time grows from 24h to 35h (+45%) → drift PR opened with title `audit: strategy drift detected YYYY-MM`, body includes Lead Time row showing baseline=24, current=35, delta=+45%, verdict=DRIFT.
- Milestone path: today=2026-08-02, milestone `2026-08-01 — 1 paying customer`, current paid_customers=0 → drift PR opened, body Milestone Status shows `2026-08-01 OVERDUE: target=1, current=0`.
- Idempotency: same month, drift detected on a 2nd dispatch in same month → first PR body is updated (not duplicated). Verify by `gh pr list --search "audit: strategy drift detected YYYY-MM"` returns 1 row.
- Edge case: paid_customers grows from 1 to 4 → NO drift triggered (asymmetric threshold).
- Edge case: previous baseline entry has `metrics.paid_customers: null` (fetch_failed) → delta calc skipped for that metric, workflow continues.

**Verification:**
- After workflow runs, baseline file has new entry.
- If drift conditions met, exactly 1 PR exists per calendar month with title pattern `audit: strategy drift detected YYYY-MM`.
- If no drift, baseline-only PR auto-merges via `bot-pr-review-merge.yml`.

---

## System-Wide Impact

- **Interaction graph:** New workflow does not invoke any existing workflow. `bot-pr-review-merge.yml` will trigger on the audit PR's `opened`/`reopened` events because filter includes `pupabobas[bot]` (post-#675).
- **Error propagation:** Metric fetch failures → `null` + `::warning::`, workflow does NOT fail. App token failure → workflow fails fast (no fallback to PUSH_TOKEN by design — visible failure surfaces credential rot). MentisDB append failure → `::warning::`, non-fatal (per fatality table).
- **State lifecycle risks:** `company/strategy-audit-baseline.json` capped at 24 entries to bound size. Idempotency check prevents duplicate-PR explosion if cron + workflow_dispatch fire on same day.
- **API surface parity:** None. New observability only.
- **Integration coverage:** First real cron run on first Monday after merge (worst case ~5 weeks out from 2026-05-03 → 2026-06-01). Manual `workflow_dispatch` immediately after merge confirms end-to-end.
- **Unchanged invariants:** `pipeline-health.yml` cadence, `bot-pr-review-merge.yml` filter, all 5 STRATEGY.md metric definitions, MentisDB chain naming convention.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Chimney HTML structure changes, scraper breaks | `null` value + `::warning::`; baseline still updates with other metrics; deferred Polar API integration fallback. Failure mode is "metric reads null", not "workflow fails". |
| App token misconfiguration (e.g., wgmesh repo not in App's selected installations) | Fail fast at App token step; `::error::` immediately visible; rollback = revert workflow file. Org-level secrets verified 2026-05-02. |
| First cron run (~2026-06-01) is also first ever drift PR — could surprise founder | First baseline = no drift possible; first drift PR can only fire on month 2 (~2026-07-06). Founder has 2 months of forewarning via this plan and merge PR. |
| `gh search` query syntax fragile — wrong query → wrong metric numbers | Test scenarios in U4 force the implementer to validate against real PR data before merge. Worst case: numbers are off but baseline-only PR (no drift) still merges; founder spots discrepancy on first manual review. |
| Audit PR auto-merges via `bot-pr-review-merge.yml` despite containing meaningful suggested edits the founder should see | Drift PR is separate title pattern (`audit: strategy drift detected ...`) — confirm `bot-pr-review-merge.yml` either explicitly excludes that pattern, OR drift PR includes label `needs-human` to block auto-merge. Implementer adds `--label needs-human` to drift `gh pr create`. Baseline-only PR (`audit: strategy baseline ...`) auto-merges fine. |

---

## Documentation / Operational Notes

- Add a 1-line entry to `STRATEGY.md` under "Documentation Plan" or similar? No — STRATEGY.md is the doc, not the operator manual. Operational note belongs in `README.md` or new `docs/operations/strategy-audit.md`. Defer doc-write to a follow-up — workflow file itself carries the comments.
- First-run note: founder should manually `workflow_dispatch` strategy-audit.yml the day this lands so the first baseline entry exists. Without it, the cron run a month later has no baseline and exits clean (no drift) but produces a confusing-looking first PR. Include this in PR description for the merge.
- Memory addition after merge: new `reference_strategy_audit.md` describing the workflow + baseline schema + drift triggers. Defer to ce-work.

---

## Sources & References

- Strategy doc: `STRATEGY.md` (just authored 2026-05-03)
- Pattern reference: `.github/workflows/pipeline-health.yml` (post-PR-#675)
- Bot filter: `.github/workflows/bot-pr-review-merge.yml` line 23
- App credentials provisioning: PR #675 (https://github.com/atvirokodosprendimai/ai-pipeline-template/pull/675) — must be merged before this plan ships, since this plan reuses the org-level App secrets that #675 established as production.
- Memory: `reference_pupabobas_app.md`, `feedback_pat_pr_email_spam.md`, `reference_mentisdb_ci_integration_pattern.md`, `feedback_check_git_index_before_commit.md`
- Public dashboard: https://chimney.beerpub.dev/
