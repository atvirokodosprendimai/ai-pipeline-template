# feat: Quackback cutover — flip the decision layer from GitHub Issues to Quackback

**Date:** 2026-06-22 · **Type:** feat · **Depth:** Deep
**Origin:** `docs/brainstorms/2026-06-21-quackback-decision-layer-requirements.md`,
`docs/plans/2026-06-21-001-feat-quackback-decision-layer-plan.md` (U9 + activation)
**Runbook:** `docs/runbooks/quackback-cutover.md`

---

## Status (2026-06-22)

- **U1 — DONE** (PR #1977 `89ed8a3`). `observation-loop.yml` both `gh issue create`
  steps gated on the `FORGE_KIND` repo var (no-op+log when `quackback`, github
  byte-unchanged, reversible). `QuackbackForge.dispatch_workflow` → no-op-and-warn
  host seam (was a latent double-create delegating to `_gh`).
  *Deviation:* the dispatch no-op landed at the forge layer, not as a guard in
  `_h_dispatch_observation_loop` — single seam, handler unchanged, conformance-covered.
- **U2 — DONE** (`4fa8d50`). `QUACKBACK_BOARD_ID` in `BOX_CONFIG_ALLOWLIST` +
  fail-closed config guard.
- **U3 — DONE** (PR #1977 `89ed8a3`). Python collector
  `wgmesh_pipeline/quackback_kpi.py` (`collect_quackback_queue_health` +
  `select_queue_health`) — posts-by-decision-status + oldest-undecided age,
  fail-closed-loud. Chose Python over bash (reuses `QuackbackClient` reads; live
  consumer is the box gather). *Deferred to U4:* wiring `select_queue_health`
  into the live `observation.py` gather (the loop is halted; built against fixtures).
- **U4 — IN PROGRESS (2026-06-22).** Drain DONE (wgmesh 0 issues / 0 PRs: 27 service/GTM
  issues + 12 PRs closed; 3 keepers #778/#729/#539 reseeded as board Open-for-Vote posts).
  Minted bot key `autobox-box` (admin UI), synced repo secret. Box flipped via `set-box-env`:
  `FORGE_KIND=quackback` + `QUACKBACK_URL/TOKEN/BOARD_ID` + `CONTROL_LOOP_ENABLED=true`,
  `OBSERVATION_LIVE=false` (shadow). Box restarted clean (config constructed, `reconcile
  seen=0` = only Accepted posts ingest = human-gated). Repo var `FORGE_KIND=quackback` set
  (mutes Actions creator). **REMAINING:** (a) flip `OBSERVATION_LIVE=true` to make the box
  the live suggestion creator (after a shadow observation cycle); (b) one e2e accept→Shipped
  verify (needs a founder vote); (c) optional store reset — stale github rows self-drain to
  terminal `failed`, bounded waste. Rollback = `FORGE_KIND=github` + re-enable workflows.

All code units merged to main and **inert** (`forge_kind` defaults to `github`).

---

## Summary

The Quackback decision-layer adapter (U1–U6, U12 of the decision-layer plan) is **merged on
main and inert** — `forge_kind` defaults to `github`, so nothing routes to Quackback yet. The
live instance (`http://89.167.62.47:3000`) is fully provisioned (board `build-suggestions`,
8 decision statuses, bot key `autobox`, `QUACKBACK_URL`/`QUACKBACK_TOKEN` repo secrets).

This plan is the **cutover** — the last unbuilt unit (U9) plus the minimum activation a safe
flip requires. The chosen shape (operator, 2026-06-22) is **box-native**: make the box's
existing observation control-loop module the sole issue/post creator, retire the Actions
workflow's raw-bash `gh issue create`, repoint the queue-health KPI off GitHub issues, then
drain → shadow-prove → flip live → verify → (reversible) rollback.

## Problem frame

The box already has a complete, forge-agnostic observation pipeline: `_cycle_observation`
runs gather → assess (Goose) → `plan_actions` → execute through `self.forge.create_issue`,
which resolves to `QuackbackForge` when `forge_kind=quackback` (sanitise wall + cross-status
dedup + tags all built in U2–U5). It runs in **shadow** today. The LIVE issue creation is a
DIFFERENT path — `.github/workflows/observation-loop.yml` creates issues via raw bash
`gh issue create` (two sites, ~L735 and ~L817). So flipping `forge_kind` alone does **not**
repoint production: the bash workflow bypasses the Python forge entirely (the same gap that
left `_h_create_issue` host-neutral but unused in the live loop).

Cutover therefore means: (1) stop the Actions workflow from creating, (2) make the box module
the sole live creator against Quackback, (3) keep the queue observable once issues leave
GitHub, (4) sequence the flip safely with a drain gate and a config-flip rollback.

## Key technical decisions

- **KTD1 — box-native creation, retire the Actions bash creator (operator choice).** The box
  `_cycle_observation` becomes the single source of new Build Suggestions; the
  `observation-loop.yml` bash `gh issue create` path is disabled. Aligns with the
  Actions=CI/CD-only retarget and reuses the merge-lane-heal cron-retirement precedent
  (box module proven in shadow, then cron retired). No new creation code — the path exists;
  this activates it and removes the competing one.
- **KTD2 — flip is a flag, not a code-default change.** `forge_kind` stays `github` in code;
  cutover sets `FORGE_KIND=quackback` (already box-config allowlisted) + `OBSERVATION_LIVE=true`
  on the box. Rollback = flip back + re-enable the workflow. The `gh` path is disabled, never
  deleted (runbook §4).
- **KTD3 — bare cutover, U8 notifications deferred (operator choice).** No founder-notification
  / SLA in this cutover. **Accepted risk:** founder attention is the new throughput gate; with
  no "posts await your vote" signal the queue can stall silently at zero builds. Mitigation:
  the U3 KPI repoint makes the stall *visible* (oldest-undecided age), and the drain gate keeps
  the GitHub lane draining in parallel during bake-in. U8 is the immediate follow-up.
- **KTD4 — KPI redesign, not a 1:1 repoint.** Quackback has no `fn:*` labels; the queue-health
  signal becomes **posts-by-decision-status** + **oldest-undecided age** on the board. PR /
  merge-rate / CI / release / stars stay on GitHub (PR side is unchanged — KTD1 of the
  decision-layer plan). Only the ISSUE-derived signals repoint.
- **KTD5 — drain before flip (operator decision, carried from 2026-06-21).** In-flight GitHub
  spec/impl issues+PRs finish-clean (drain to ~0) before the flip, so no work is stranded on
  the old path. Verified at cutover time, not assumed here.

---

## High-level technical design

```
BEFORE (today, inert):
  box _cycle_observation (SHADOW) ─ plans creates, logs, executes nothing
  observation-loop.yml (Actions, LIVE) ── raw bash `gh issue create` ──▶ GitHub Issues
  config.forge_kind = github   QuackbackForge merged but unused

AFTER cutover (forge_kind=quackback, observation_live=true):
  observation-loop.yml ── creation DISABLED (rollback-reversible) ─────▶ (no writes)
  box _cycle_observation (LIVE)
     gather ─ assess(Goose) ─ plan_actions ─ executor.create_issue
                                                   │ make_forge(quackback)
                                                   ▼
                                        QuackbackForge.create_issue
                                        (sanitise wall + cross-status dedup + tags)
                                                   │  POST /api/v1/posts
                                                   ▼
                              Quackback board `build-suggestions` (Open for Vote)
                                                   │  founder: Accepted for Build
                                                   ▼
                              box claims → spec→impl→PR (GitHub, unchanged)
                                                   │  judge-gated auto-merge
                                                   ▼            box mirrors status
                                        merged ───────────────▶ Quackback: Shipped

  KPI:  collect-github (PR/CI/release/stars)  +  collect-quackback (posts-by-status, oldest-undecided age)
```

---

## Implementation units

### U1. Retire the Actions observation issue-creation; box becomes sole creator — ✅ DONE (PR #1977 `89ed8a3`)
**Goal:** `observation-loop.yml` stops creating issues so the box `_cycle_observation` module
is the single source — no double-create, no raw-bash `gh issue create`.
**Requirements:** KTD1, origin "HARD REPLACE day one" (decision-layer brainstorm). **Dependencies:** none.
**Files:** `.github/workflows/observation-loop.yml`, `pipeline/wgmesh_pipeline/control_loop/executor.py`
(guard `_h_dispatch_observation_loop`), `pipeline/tests/test_control_loop_executor.py`.
**Approach:** Flag-guard the two `gh issue create` sites (~L735 create, ~L817 needs-human) so
they no-op when the box owns creation — gate on a workflow input / `FORGE_KIND` env so the
disable is reversible (rollback re-enables). Prefer disabling the *creation steps* over deleting
the workflow: the gather/assess/close steps and manual dispatch stay available for rollback.
Guard the selfheal `dispatch_observation_loop` action so an idle signal doesn't fire a
creation-disabled workflow when `forge_kind=quackback` (no-op + log, mirroring the Gitea
host-seam pattern). Mirror the merge-lane-heal cron-retirement shape: prove the box path in
shadow (U4) before the workflow is muted.
**Execution note:** characterization-first — `observation-loop.yml` is load-bearing infra;
assert the GitHub creation path is byte-unchanged when the guard defaults to the github/enabled
value, and only the quackback/disabled branch no-ops.
**Patterns to follow:** the merge-lane-heal cron retirement (`project_merge_lane_heal_to_box`),
the cloudroof `service`-input guard pattern (`set-box-env.yml` resolve step), Gitea host-seam
no-op for `dispatch_workflow`.
**Test scenarios:** guard defaults (github) → both `gh issue create` sites still fire (characterization);
guard=quackback/disabled → creation sites no-op, gather/assess/close unaffected; YAML valid;
`_h_dispatch_observation_loop` no-ops (returns without dispatch) when `forge_kind=quackback`,
still dispatches for github. `Covers: box is the sole creator post-cutover.`

### U2. Propagate Quackback config to the box (board id + creds + flags) — ✅ DONE (`4fa8d50`)
**Goal:** the box env carries everything `make_forge(quackback)` needs, and constructing it
fails loudly if a credential is missing.
**Requirements:** KTD2, decision-layer U1 (config). **Dependencies:** none.
**Files:** `pipeline/wgmesh_pipeline/config.py` (box-config allowlist + optional board-id field),
`pipeline/tests/test_config.py`; box env via `set-box-env.yml` / provision (operational, U4).
**Approach:** Add `QUACKBACK_BOARD_ID` to `BOX_CONFIG_ALLOWLIST` (non-secret board id; the
adapter reads it from env via `BOARD_ID_ENV`). `QUACKBACK_URL` / `QUACKBACK_TOKEN` are secrets —
they reach the box env through provision or `set-box-env` (both are flag-charset-safe:
`https://…` and `qb_…`), NOT box-config.json (allowlist already excludes secret-shaped keys).
Confirm `load_config` already fails closed when `forge_kind=quackback` and URL/token are unset
(decision-layer U1) — add a board-id presence check at the same seam if absent. No core forge
change; this is wiring + a guard.
**Execution note:** test-first on the config guard.
**Patterns to follow:** existing `forge_kind=quackback` fail-closed block in `config.py`,
`BOX_CONFIG_ALLOWLIST` entries (`FORGE_KIND`, `MERGE_LANE_HEAL_LIVE`), the cloudroof `SURFACE_HOME`
allowlist addition.
**Test scenarios:** `forge_kind=quackback` + missing `QUACKBACK_URL`/`QUACKBACK_TOKEN` → raises
at config construction (existing); + missing `QUACKBACK_BOARD_ID` → raises (or adapter raises at
ctor — assert whichever seam owns it); `QUACKBACK_BOARD_ID` passes through box-config allowlist;
`forge_kind=github` → none required, unchanged. `Covers: box constructs QuackbackForge or fails loud.`

### U3. Repoint queue-health KPI from GitHub issues to Quackback posts — ✅ DONE (PR #1977 `89ed8a3`)
**Goal:** the pulse / observation queue-health signal stays meaningful once issues live in
Quackback — measure posts-by-decision-status and oldest-undecided age, not GitHub issue labels.
**Requirements:** KTD4, decision-layer "repoint pulse open-age KPI off GH Issues" (load-bearing).
**Dependencies:** U2 (board id + creds available). 
**Files:** `company/scripts/collect-quackback.sh` (new) OR a Python collector under
`pipeline/wgmesh_pipeline/`, wiring in `company/scripts/collect-github.sh` (gate the issue-derived
block on `forge_kind`) or the box observation/pulse gather; tests
(`pipeline/tests/test_quackback_kpi.py`).
**Approach:** When `forge_kind=quackback`, the ISSUE-derived signals (currently `issues_by_label`
from `search/issues`) are replaced by board reads: count posts per decision status
(`GET /api/v1/posts?status=<slug>` per the 8 statuses — slug filter, VERIFIED) and compute the
age of the oldest post still in `open_for_vote` / `needs_refinement` (the founder-attention
backlog). PR / merge-rate / CI / release / stars **stay GitHub** (PR side unchanged). Emit the
same JSON shape the pulse/observation consumer expects, with the queue block sourced from
Quackback. Reads fail-closed-loud for the gating-relevant counts, best-effort for cosmetic ones.
**Execution note:** test-first against recorded Quackback API fixtures (the runbook's VERIFIED
shapes) — no live calls in tests.
**Patterns to follow:** `company/scripts/collect-github.sh` (signal-collector shape + JSON
envelope), `forge/quackback_client.py` (status-slug filter, cursor pagination, fail-closed read),
the Mixpost KPI precedent (`reference_mixpost_social_drip_integration`) for a service-scope KPI.
**Test scenarios:** posts-by-status maps the 8 slugs to counts; oldest-undecided age computed
from `createdAt` of the oldest `open_for_vote` post; empty board → zero counts, null age (not error);
API error on a gating count → fail-closed-loud (non-zero / logged), not silent zero; `forge_kind=github`
→ collector unchanged (GitHub path). `Covers KTD4: the queue stays observable post-cutover.`

### U4. Drain → shadow-prove → flip live → verify → rollback (operational) — ⏳ PENDING (operator; box halted + creds)
**Goal:** one real cutover: in-flight GitHub work drained, box proven in shadow against the live
instance, flag flipped, end-to-end accept→build→merge→Shipped confirmed, with a tested rollback.
**Requirements:** KTD2, KTD3, KTD5, origin verification (decision-layer runbook §3–4).
**Dependencies:** U1, U2, U3.
**Files:** `docs/runbooks/quackback-cutover.md` (fill §3 cutover + §4 rollback with the box-native
sequence). No app code.
**Approach:** (1) **Drain** in-flight GitHub spec/impl issues+PRs to ~0 (operator gate). (2)
**Shadow-prove**: with `FORGE_KIND=quackback` but `OBSERVATION_LIVE=false`, run a box observation
cycle and confirm it *plans* Quackback-bound creates (board id resolves, sanitise+dedup run, no
GitHub writes) — mirroring the merge-lane-heal shadow proof. (3) **Flip**: `set-box-env` →
`FORGE_KIND=quackback`, `OBSERVATION_LIVE=true`, `QUACKBACK_BOARD_ID=<board>` (+ confirm
`QUACKBACK_URL`/`QUACKBACK_TOKEN` present); restart. (4) **Disable** the Actions creation (U1 guard
on). (5) **Verify**: next observation cycle creates a Quackback post and **zero** GitHub issues;
one full accept→build→merge→Shipped cycle completes (founder flips Accepted for Build → box claims
→ PR → judge auto-merge → box mirrors Shipped). (6) **Rollback rehearsal**: document that
`FORGE_KIND=github` + re-enable the workflow restores the old path (reseed the drained backlog if
needed).
**Execution note:** shadow-prove before the live flip, mirroring the merge-lane-heal cutover discipline.
**Test scenarios:** Test expectation: none — operational verification (the runbook checklist + the
live smoke is the proof). Verification: a Quackback post created by the box with zero new GitHub
issues in the same window; one e2e accept→Shipped cycle; rollback flip observed to re-create on GitHub.

---

## Scope boundaries

- **In:** retire the Actions bash issue-creation (box-native); box config propagation +
  fail-closed guard; queue-health KPI repoint to Quackback; the drain→flip→verify→rollback
  operation + runbook.
- **Deferred to Follow-Up Work:** U8 founder notifications + 48h SLA (immediate next — the
  silent-stall mitigation, KTD3); U7 decision→Langfuse audit score + decision dataset; R4 PR-body
  post-URL wiring; U10/U11 vote-rerank + in-context steering.
- **Outside this cutover's identity:** the adapter design (U1–U6/U12, already merged); the PR/merge
  side (stays GitHub); the cloudroof-funnel accept-gate (a *downstream consumer* this cutover
  unblocks — `project_cloudroof_service_funnel` U6 — not in scope here).

## Sequencing

U1, U2, U3 are independent and parallelizable (U3 reads config from U2 but can be built against
fixtures). U4 depends on all three and is the operator-run cutover. Shadow-prove (U4 step 2) gates
the live flip, exactly as the merge-lane-heal cutover did.

## Risks & dependencies

- **Box observation gather parity.** The box `observation_gather` may be thinner than the Actions
  workflow's signal gather ("honest degradation" noted in `control_loop/__init__`). Risk: post-cutover
  the box surfaces fewer/weaker suggestions than the bash loop did. Mitigation: shadow-prove (U4)
  compares planned creates against a recent workflow run before muting it; if gather is thin, widen
  it as a fast follow rather than blocking cutover.
- **Silent founder stall (KTD3).** No notification → posts can sit in Open for Vote unbuilt.
  Mitigation: U3 oldest-undecided-age KPI makes it visible; U8 is the immediate follow-up.
- **Creds not yet on the box.** `QUACKBACK_*` secrets were set as repo secrets 2026-06-21, AFTER the
  box's last `set-box-env` — the box env may lack them. U4 step 3 explicitly propagates them; U2's
  fail-closed guard turns a miss into a loud config error, not a silent github fallback.
- **Double-create window.** If the box goes live before the workflow is muted, both create. U4
  sequences mute (step 4) immediately after flip (step 3) and verifies zero GitHub issues (step 5).
- **Rollback completeness.** Drained GitHub backlog must be reseedable on rollback (runbook §4).

## Open questions (deferred to execution)

- Exact disable mechanism for `observation-loop.yml` creation: workflow input vs. `FORGE_KIND`
  env read in the step vs. schedule-disable (U1 picks during implementation; reversibility is the
  constraint).
- Whether the KPI collector lands as bash (`collect-quackback.sh`, mirrors `collect-github.sh`) or
  Python (reuses `QuackbackClient` read paths) — U3 decides by where the pulse gather consumes it.
- Drain threshold ("~0") and timing — operator call at cutover (U4).
