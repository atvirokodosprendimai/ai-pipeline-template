---
title: "feat: instrument remaining GitHub Actions workflows with MentisDB thought-append"
type: feat
status: active
date: 2026-04-27
---

# feat: instrument remaining GitHub Actions workflows with MentisDB thought-append

## Overview

Wire the remaining ten lifecycle workflows in `atvirokodosprendimai/ai-pipeline-template` to append structured thoughts to MentisDB at `mem.beerpub.dev`. Three workflows already integrate (`mentisdb-smoketest.yml` daily round-trip, `observation-loop.yml` strategic Insight, `terraform-deploy.yml` consumes `MENTISDB_PASSWORD` as a TF input). The remainder run silently — there is no agent-memory record of CI lifecycle events (PR review/merge outcomes, spec validations, triage assignments, build closures, self-heal cycles, endpoint health failures).

After this work, every meaningful CI event in this repo writes a typed thought into the `ai-pipeline-template` chain, restoring continuity for downstream agents that read MentisDB to reason about pipeline state.

---

## Problem Frame

The pipeline emits dozens of events per day across 14 workflows. Of those, only the daily strategic loop and a smoketest write to MentisDB. The rest of the lifecycle — PR triage, spec validation, build dispatch, merge closure, self-healing, endpoint health — produces no durable agent-memory trace beyond `gh run` logs that age out and lack semantic structure.

Memory note `reference_mentisdb_ci_integration_pattern.md` already defines the canonical step shape, thought-type table, fatality decision rules, and chain naming convention. This plan is a mechanical rollout of that pattern across the remaining workflows; no architectural decisions are open.

Skip `sync-labels.yml` — fires on every label sync, low signal, would generate noise.

---

## Requirements Trace

- R1. Every lifecycle workflow in scope appends a thought to MentisDB on terminal job state (`success` or `failure`), via an `if: always()` step.
- R2. All appends use `chain_key: "ai-pipeline-template"` to keep this repo's CI activity in one queryable chain (per pattern doc).
- R3. Append failures are non-fatal for high-frequency / observability workflows (per fatality table in pattern doc) — failures emit `::warning::` instead of failing the workflow.
- R4. Thought type, importance, tags, and content are chosen per the pattern doc table for each workflow's event class.
- R5. No new secrets are introduced. Reuse existing org-level `MENTISDB_URL` / `MENTISDB_USER` / `MENTISDB_PASSWORD` (visibility: selected → ai-pipeline-template + wgmesh).
- R6. Existing wired workflows (`observation-loop.yml`, `mentisdb-smoketest.yml`, `terraform-deploy.yml`) are not modified.
- R7. Verification: at least one instrumented workflow per event-class cluster is dispatched manually post-merge, and the resulting thought appears in a MentisDB `/v1/search` against `chain_key=ai-pipeline-template`.

---

## Scope Boundaries

- Not modifying the three already-wired workflows.
- Not instrumenting `sync-labels.yml` (low signal, high frequency).
- Not changing the existing pattern (chain naming, thought_type table, step shape) — this plan consumes it, does not redesign it.
- Not adding new MentisDB secrets, rotating existing ones, or changing org secret visibility.
- Not adding cross-repo querying or cross-chain references — out of scope; the chain remains repo-local.
- Not introducing a reusable composite action or workflow template — explicit per-workflow steps preserve readability and match the pattern doc's recommendation. (Reusable action is an explicit non-goal — see Open Questions / Resolved.)

---

## Context & Research

### Relevant Code and Patterns

- `.github/workflows/observation-loop.yml` (lines ~415-490) — reference implementation: `if: always()`, env block with three secrets, jq-built JSON payload, curl with `--fail-with-body`, fatal append (no `||`).
- `.github/workflows/mentisdb-smoketest.yml` — reference for round-trip verification (POST `/v1/thoughts` then POST `/v1/search`, grep for marker).
- `.github/workflows/terraform-deploy.yml` (lines 69-121) — reference for `MENTISDB_PASSWORD` consumed as TF var (different concern; not modified).

### Institutional Learnings

- `memory/reference_mentisdb_ci_integration_pattern.md` — canonical step shape, thought-type-by-event table, fatality rules, onboarding checklist. **Authoritative source for this plan.**
- `memory/reference_org_secrets_inventory.md` — confirms `MENTISDB_*` are org-level with `visibility: selected` already including ai-pipeline-template.
- `memory/feedback_mentisdb_no_rest_auth.md` — REST/MCP have zero built-in auth; nginx Basic Auth is the gate. Step shape must include `-u "$MENTISDB_USER:$MENTISDB_PASSWORD"`.
- `memory/feedback_check_git_index_before_commit.md` — `git status --short` first column = staged; pre-staged unrelated files hitch onto bare commit.

### External References

- None required — the pattern is fully internal and battle-tested in `observation-loop.yml` and the wgmesh sister repo.

---

## Key Technical Decisions

- **Per-workflow inline step over reusable composite action:** The append step is ~15 lines per workflow. A composite action would centralize the curl+jq logic but obscures per-workflow content/tag choices and adds an indirection layer. Pattern doc shows wgmesh + ai-pipeline-template both use inline steps. Maintain consistency.
- **Non-fatal for all 10 workflows in scope:** None of these workflows are release events or low-frequency metrics rollups. They are operational lifecycle events where the build/merge outcome is the primary signal and MentisDB observability is supplementary. A MentisDB hiccup must not block PR merges or health checks. Append `|| echo "::warning::mentisdb append failed (non-fatal)"`.
- **Single chain `ai-pipeline-template` for all 10 workflows:** Pattern doc says one chain per repo. Workflow identity is preserved via `agent_id` (workflow filename without extension) and tags.
- **`if: always()` placement:** Append step must run regardless of preceding step outcomes so failure thoughts get recorded. Place as the last step in each job.
- **`agent_id` / `agent_name` convention:** Use the workflow's filename minus `.yml` extension (e.g., `bot-pr-review-merge`, `health-check`). Matches existing `observation-loop.yml` convention.
- **Importance values from pattern doc table:** Do not invent new importance scores. ActionTaken=0.5, TaskComplete=0.7, Mistake=0.7-0.8, Insight=0.4, Correction=0.6.

---

## Open Questions

### Resolved During Planning

- **Q: Build a reusable composite action?** No. Pattern doc + existing impls all use inline steps. Inline keeps per-workflow content/tag choices visible at the point of use.
- **Q: Append on every health-check tick (every 15 min) or only on failure?** Only on failure. Health-check fires 96×/day — successful checks would flood the chain with noise. Failure events are the signal worth memorializing. (Pattern doc: "Mistake on fail only".)
- **Q: Append for `sync-labels.yml`?** No. Pure mechanical sync, no semantic event worth a thought.
- **Q: How to handle PRs to non-bot authors in `bot-pr-review-merge.yml`?** The workflow's existing `if:` already gates on bot authorship. The append step inherits that gate by living inside the same job — no extra logic needed.
- **Q: What if `MENTISDB_*` secrets aren't visible to this repo?** Memory confirms they are. Smoketest workflow validates this daily. No secrets work needed.

### Deferred to Implementation

- **Tag choice per workflow:** The pattern doc gives the structure (`[<repo>, <event-type>, <outcome>]`). Exact tag strings are best chosen at the point of edit so they reflect the workflow's actual semantics. Implementer should mirror the wording used in the workflow's existing job/step names.
- **Whether to include PR number, issue number, or commit SHA in `content`:** Decide per workflow based on what makes the search result useful. Default: include the GitHub run URL (already in pattern), plus the most relevant identifier from the trigger event (PR # for PR-triggered, issue # for issue-triggered, schedule timestamp for scheduled).

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

Each instrumented workflow gains exactly one new step at the end of its existing job (or each job, when there are multiple parallel jobs whose outcomes both matter). The shape is constant; the contents vary:

```yaml
- name: Append <event> to MentisDB
  if: always()
  env:
    MENTISDB_URL: ${{ secrets.MENTISDB_URL }}
    MENTISDB_USER: ${{ secrets.MENTISDB_USER }}
    MENTISDB_PASSWORD: ${{ secrets.MENTISDB_PASSWORD }}
    OUTCOME: ${{ job.status }}
  run: |
    set -euo pipefail
    case "$OUTCOME" in
      success)   TYPE="<success-type>"; IMP="<success-imp>" ;;
      failure)   TYPE="Mistake";        IMP="0.8"           ;;
      cancelled) TYPE="Mistake";        IMP="0.6"           ;;
      *)         TYPE="Mistake";        IMP="0.7"           ;;
    esac
    PAYLOAD=$(jq -nc \
      --arg type "$TYPE" \
      --arg outcome "$OUTCOME" \
      --arg run_url "${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}" \
      --arg imp "$IMP" \
      '{
        chain_key: "ai-pipeline-template",
        agent_id: "<workflow-id>",
        agent_name: "<workflow-id>",
        thought_type: $type,
        content: ("<event description with identifiers> — " + $outcome + " (" + $run_url + ")"),
        tags: ["ai-pipeline-template", "<event-type>", $outcome],
        importance: ($imp | tonumber)
      }')
    curl --fail-with-body --silent --show-error --max-time 15 \
      -u "$MENTISDB_USER:$MENTISDB_PASSWORD" \
      -X POST -H 'Content-Type: application/json' \
      -d "$PAYLOAD" "$MENTISDB_URL/v1/thoughts" \
      || echo "::warning::mentisdb append failed (non-fatal)"
```

Per-workflow variation lives only in: `<event>` (step name), `<workflow-id>` (filename stem), `<success-type>`/`<success-imp>` (per pattern table), `<event description>`, `<event-type>` tag, identifiers in content. Health-check is the one exception — it skips the append entirely on success and only records on failure.

---

## Implementation Units

- U1. **Bot-authored PR lifecycle workflows**

**Goal:** Instrument the three workflows that handle bot/Copilot PR lifecycle (open → review → merge) so each PR's outcome is recorded.

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** None (org secrets already provisioned).

**Files:**
- Modify: `.github/workflows/bot-pr-review-merge.yml`
- Modify: `.github/workflows/heartbeat-pr-automerge.yml`
- Modify: `.github/workflows/copilot-undraft.yml`

**Approach:**
- For `bot-pr-review-merge.yml`: append at end of `review-merge` job. `agent_id="bot-pr-review-merge"`. Success → `TaskComplete` (imp 0.7), failure → `Mistake` (imp 0.8). Content includes PR number + author. Tags: `["ai-pipeline-template", "pr-review-merge", $outcome]`.
- For `heartbeat-pr-automerge.yml`: append at end of `validate-and-merge` job. `agent_id="heartbeat-pr-automerge"`. Success → `TaskComplete` (imp 0.7), failure → `Mistake` (imp 0.8). Content includes PR number + title. Tags: `["ai-pipeline-template", "heartbeat-merge", $outcome]`.
- For `copilot-undraft.yml`: append at end of the undraft job. `agent_id="copilot-undraft"`. Success → `ActionTaken` (imp 0.5), failure → `Mistake` (imp 0.7). Content includes PR number. Tags: `["ai-pipeline-template", "spec-undraft", $outcome]`.
- All three: non-fatal append (`|| echo "::warning::..."`).

**Patterns to follow:**
- `observation-loop.yml` lines ~415-490 — env block, jq payload, curl invocation.
- `reference_mentisdb_ci_integration_pattern.md` — Step shape section.

**Test scenarios:**
- Happy path: trigger via existing live event (real bot PR opens) — confirm `TaskComplete` thought appears in chain `ai-pipeline-template` with PR# in content.
- Edge case: workflow runs but the merge condition (`if:`) gates it out — append step still runs (`if: always()`) and records the gate-out as success of an empty job. (Acceptable; the run URL points to a no-op run.)
- Error path: simulate MentisDB unavailability by manually editing `MENTISDB_URL` to a bad host in a workflow_dispatch test branch — confirm workflow exits 0 with `::warning::` in logs (non-fatal verified).
- Integration: end-to-end run on a real bot PR after merge — search MentisDB for `chain_key=ai-pipeline-template tags_any=["pr-review-merge"]` and confirm the run URL matches.

**Verification:**
- All three workflows pass `actionlint` (or equivalent YAML validation; if no actionlint, GitHub's own validator on push is sufficient).
- After merge, the next bot PR triggers each workflow and a `TaskComplete` thought lands in the chain.

---

- U2. **Spec/build pipeline workflows**

**Goal:** Instrument the three workflows that drive the spec → approve → build pipeline so each transition is durable.

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** None.

**Files:**
- Modify: `.github/workflows/spec-validation.yml`
- Modify: `.github/workflows/approve-build.yml`
- Modify: `.github/workflows/spec-merged-build.yml`

**Approach:**
- For `spec-validation.yml`: append at end of validation job. `agent_id="spec-validation"`. Success → `Correction` (imp 0.6) when validation auto-fixes/labels; `ActionTaken` (imp 0.5) for plain pass; failure → `Mistake` (imp 0.7). Choose `Correction` when validation produced an `approved-for-build` or similar state-changing label, `ActionTaken` otherwise — implementer decides based on the workflow's existing branches. Content includes spec PR # and validation outcome label. Tags: `["ai-pipeline-template", "spec-validation", $outcome]`.
- For `approve-build.yml`: append at end of approval job. `agent_id="approve-build"`. Success → `ActionTaken` (imp 0.5), failure → `Mistake` (imp 0.7). Content includes PR # + reviewer. Tags: `["ai-pipeline-template", "spec-approval", $outcome]`.
- For `spec-merged-build.yml`: append at end of build dispatch job. `agent_id="spec-merged-build"`. Success → `ActionTaken` (imp 0.5; the actual build happens elsewhere), failure → `Mistake` (imp 0.7). Content includes spec PR # + dispatched build target. Tags: `["ai-pipeline-template", "spec-merge-build", $outcome]`.
- All three: non-fatal append.

**Patterns to follow:**
- Same as U1.

**Test scenarios:**
- Happy path: spec PR opened → `spec-validation` runs → `ActionTaken` or `Correction` thought lands.
- Happy path: spec PR approved + auto-merged → `approve-build` runs → `ActionTaken` thought lands.
- Happy path: spec PR merged → `spec-merged-build` dispatches downstream build → `ActionTaken` thought lands.
- Edge case: validation runs on a PR with no actionable changes (`paths` filter matched but content unchanged) — append still records the no-op run with `success` outcome.
- Error path: spec validation fails (invalid spec format) — `Mistake` thought with imp 0.8 lands; main workflow still surfaces failure normally.
- Integration: full spec lifecycle on a test issue (open spec PR → validation → approval → merge → build dispatch) → all three thoughts present in chain with correct outcome ordering.

**Verification:**
- All three workflows pass actionlint.
- A spec PR run produces three thoughts (one per workflow) tagged `spec-validation`, `spec-approval`, `spec-merge-build`.

---

- U3. **Issue lifecycle workflows**

**Goal:** Instrument the two workflows that handle issue triage assignment and impl-PR closure so the issue → spec → impl → close arc is recorded.

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** None.

**Files:**
- Modify: `.github/workflows/copilot-triage.yml`
- Modify: `.github/workflows/impl-merged-close.yml`

**Approach:**
- For `copilot-triage.yml`: append at end of `triage` job. `agent_id="copilot-triage"`. Success → `ActionTaken` (imp 0.5), failure → `Mistake` (imp 0.7). Content includes issue # + triggering label. Tags: `["ai-pipeline-template", "issue-triage", $outcome]`.
- For `impl-merged-close.yml`: append at end of close job. `agent_id="impl-merged-close"`. Success → `TaskComplete` (imp 0.7) — closing an impl PR completes a unit of work, failure → `Mistake` (imp 0.7). Content includes PR # + linked issue # (if extractable from PR title). Tags: `["ai-pipeline-template", "impl-close", $outcome]`.
- Both: non-fatal append.

**Patterns to follow:**
- Same as U1.

**Test scenarios:**
- Happy path: file an issue with `bug` label → `copilot-triage` fires → `ActionTaken` thought lands with issue # in content.
- Happy path: bot opens impl PR → human merges → `impl-merged-close` fires → `TaskComplete` thought lands.
- Edge case: triage workflow's `if:` gate skips the job (e.g., issue already has `copilot-triaging` label) — `if: always()` still runs the append, recording a no-op run as success. (Acceptable.)
- Error path: `gh` token expired during triage → workflow fails → `Mistake` thought lands; original failure surfaces in logs.
- Integration: full issue → triage → spec → build → impl → close cycle on a test issue → both U3 thoughts present plus the U2 spec-pipeline thoughts → query by `tags_any=["issue-triage","impl-close"]` returns both.

**Verification:**
- Both workflows pass actionlint.
- A real issue lifecycle produces both thoughts tagged correctly.

---

- U4. **Self-healing & observability workflows**

**Goal:** Instrument the two workflows that monitor pipeline and infrastructure health so failures and self-heal cycles are recorded.

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** None.

**Files:**
- Modify: `.github/workflows/pipeline-health.yml`
- Modify: `.github/workflows/health-check.yml`

**Approach:**
- For `pipeline-health.yml`: append at end of health-check job. `agent_id="pipeline-health"`. Success → `Insight` (imp 0.4) — observation about pipeline state, failure → `Mistake` (imp 0.7). Content includes brief state summary (e.g., stale-PR count or issue-backlog stat from existing workflow output if exposed; otherwise just outcome + timestamp). Tags: `["ai-pipeline-template", "pipeline-health", $outcome]`.
- For `health-check.yml`: **skip append on success.** Only append on failure (workflow runs every 15 min — success would flood the chain). `agent_id="health-check"`. Failure → `Mistake` (imp 0.7). Content includes the down service names from existing `down_names` output. Tags: `["ai-pipeline-template", "endpoint-health", "failure"]`. Use `if: failure() || cancelled()` instead of `if: always()` for this one workflow.
- Both: non-fatal append.

**Patterns to follow:**
- `observation-loop.yml` for pipeline-health.
- Pattern doc fatality table: this is the explicit "Mistake on fail only" case.

**Test scenarios:**
- Happy path (pipeline-health): scheduled run completes → `Insight` thought lands every 2 hours.
- Happy path (health-check, success): all endpoints up → no thought appended (verified by absence in chain after success run).
- Error path (health-check, failure): one endpoint down (simulate by editing `health.json` to a bad URL on a test branch + `workflow_dispatch`) → `Mistake` thought lands with the down service name in content.
- Edge case (pipeline-health): scheduled run aborted mid-execution → `Mistake` thought (cancelled outcome); main workflow's existing alert behavior unchanged.
- Integration: query chain after 24h with `tags_any=["pipeline-health"]` — expect ~12 Insight thoughts (one per 2h scheduled run), zero Mistake thoughts assuming healthy day.

**Verification:**
- Both workflows pass actionlint.
- After deployment, `pipeline-health.yml` writes one thought per scheduled run; `health-check.yml` writes zero thoughts during a healthy window.

---

- U5. **Post-merge verification dispatch + chain query**

**Goal:** Confirm the rollout works end-to-end by manually dispatching one workflow per cluster and querying MentisDB for the resulting thoughts.

**Requirements:** R7

**Dependencies:** U1, U2, U3, U4 all merged to `main`.

**Files:**
- No file changes. Verification is operational.

**Approach:**
- After merge, manually trigger via `gh workflow run` (or wait for natural triggers) at least one workflow per cluster:
  - U1 cluster: any of the three (heartbeat-pr-automerge fires on the merge of this PR itself, providing natural verification).
  - U2 cluster: dispatch `spec-validation` against an existing closed spec PR or wait for next bot spec.
  - U3 cluster: file a test issue with `needs-triage` label, then close manually.
  - U4 cluster: `gh workflow run pipeline-health.yml` and `gh workflow run health-check.yml`.
- For each, run the verification curl from `reference_mentisdb_ci_integration_pattern.md` "Verification queries" section, scoped to `chain_key=ai-pipeline-template` and the relevant tag, and confirm the run_url in content matches the dispatched run.

**Test scenarios:**
- Test expectation: none — this unit is operational verification, no code changes.

**Verification:**
- For each of the four clusters, at least one thought appears in the chain with the run_url matching a dispatched run.
- No workflow failed due to mentisdb append (check Actions tab for `::warning::mentisdb append failed` — if any appear, investigate connectivity but workflow itself should still be green).

---

## System-Wide Impact

- **Interaction graph:** Each workflow gains one trailing step. No cross-workflow coupling, no shared state. Failure of the append step does not cascade.
- **Error propagation:** Append failures are absorbed by `|| echo "::warning::..."`. The workflow's primary outcome (build pass/fail, merge success, etc.) is unaffected.
- **State lifecycle risks:** None. MentisDB writes are idempotent in the sense that duplicates are recorded as duplicate thoughts — they pollute the chain but cause no incorrect behavior. Risk if a workflow retries: duplicate thoughts. Mitigation: pattern doc accepts this; queries can dedup by `run_url`.
- **API surface parity:** No external API surface change. The only consumer of the new thoughts is MentisDB, already serving wgmesh + this repo's existing two integrations.
- **Integration coverage:** The integration is a single curl POST. Unit tests are not meaningful here. End-to-end verification via U5.
- **Unchanged invariants:** `observation-loop.yml`, `mentisdb-smoketest.yml`, `terraform-deploy.yml` are not modified. `sync-labels.yml` remains uninstrumented by design. Org secret `MENTISDB_*` values, visibility, and rotation cadence unchanged. Workflow trigger conditions, permissions blocks, concurrency groups unchanged.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| MentisDB outage during rollout would mass-warning every workflow run. | Non-fatal append + `--max-time 15` curl timeout. Workflows still pass. Smoketest workflow (already wired) surfaces sustained outage as its own failure. |
| Health-check workflow firing every 15 min could flood chain even with failure-only append, if many endpoints flap simultaneously. | Per pattern: failure-only append. If flapping becomes an issue, add a debounce (e.g., only append if same down_names persisted across two consecutive runs). Out of scope for this plan; revisit if observed. |
| `job.status` value semantics could differ between matrix jobs and single-job workflows. | All instrumented workflows in scope are single-job. Confirmed via existing `observation-loop.yml` precedent. If a multi-job workflow is later added, append step needs to be added to each job individually. |
| Org secret `visibility: selected` might silently exclude this repo. | Memory confirms inclusion. Existing `mentisdb-smoketest.yml` runs daily and would have failed if visibility were wrong. No additional check needed. |
| Implementer might forget to use `if: always()` on a step, causing failure thoughts to never land. | Per-unit Approach explicitly states `if: always()` (or `if: failure() || cancelled()` for health-check). Verification step in U5 catches missing thoughts on intentionally failed test runs. |

---

## Documentation / Operational Notes

- Update `memory/reference_mentisdb_ci_integration_pattern.md` after rollout to reflect the new "instrumented workflows" list (currently lists 2; will list 12 of 14). Defer the memory update to post-merge.
- No runbook changes — failure modes are the same as before, just now also visible in MentisDB.
- No monitoring changes — existing GitHub Actions failure notifications remain primary alert channel; MentisDB is supplementary.

---

## Sources & References

- **Pattern doc (authoritative):** `memory/reference_mentisdb_ci_integration_pattern.md`
- **Reference workflow:** `.github/workflows/observation-loop.yml`
- **Reference smoketest:** `.github/workflows/mentisdb-smoketest.yml`
- **Org secrets inventory:** `memory/reference_org_secrets_inventory.md`
- **Auth gotcha:** `memory/feedback_mentisdb_no_rest_auth.md`
- **Sister repo precedent:** `atvirokodosprendimai/wgmesh` PR #535 (instrumented release.yml, agent-metrics-report.yml, goose-build.yml)
- **This repo's prior instrumentation PR:** `atvirokodosprendimai/ai-pipeline-template` PR #596 (observation-loop append)
