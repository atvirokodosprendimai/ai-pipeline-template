---
title: "feat: box auto-merge via awaiting-merge state (U4 of judge-gated automerge)"
type: feat
date: 2026-06-20
depth: deep
origin: docs/plans/2026-06-20-005-feat-judge-gated-automerge-plan.md (U4)
---

# feat: box enables auto-merge, steps away — `awaiting-merge` state

Meta-repo (`ai-pipeline-template`, `pipeline/wgmesh_pipeline/`). U4 of the judge-gated automerge
program. U1 (judge module #1916), U2 (wgmesh `impl-judge` check #796), U3 (wgmesh ruleset → required
checks, review dropped) are done — and **proven**: #795 merged on the gate with no approval.

## Summary

Today the box self-merges at the `reviewed` stage: `apply_gate_side_effects` runs
`merge_gate.ensure_mergeable` (CI green **+ a non-author approval**), and with no reviewer identity
every impl PR escalates instead of merging — convergence-stall layer 3. Now the wgmesh
`protect-main` ruleset gates merges on the **`impl-judge` fail-closed CI check** (+ build + status),
so the box should stop self-merging and instead **enable GitHub auto-merge** on its impl PR and step
away — the forge merges when the judge passes.

The trap: the poller's `reviewed → merged` transition fires on `decision == "merge"`. If the box
marked the issue **merged** at the moment it *enables* auto-merge, a later `impl-judge` FAIL (PR
stays open) leaves a **phantom-completed** issue — the false-completion class this pipeline exists to
prevent. So U4 adds a non-terminal **`awaiting_merge`** stage: the box enables auto-merge and parks
the issue there; a later poll transitions it to terminal `merged` **only when the PR actually
merges**, or escalates if it closed unmerged or sat too long (a sustained judge FAIL).

## Problem Frame

- **Now:** `reviewed` → `ensure_mergeable` (needs approval) → escalate; box never merges.
- **Goal:** `reviewed` → enable auto-merge → `awaiting_merge`; forge merges on `impl-judge` PASS;
  box reconciles to `merged` on real merge, escalates on close-unmerged or staleness.
- **Constraint (cardinal):** never record `merged` while the PR is unmerged (no phantom completion).
- **Safety floor:** the box currently escalates at `reviewed` (no false merges); shipping U4 must
  not regress that. `mode=shadow` keeps everything dry-run.

---

## Scope Boundaries

**In scope** — `pipeline/wgmesh_pipeline/`: a `client.enable_auto_merge`, the gate side-effect swap,
the `awaiting_merge` state + transitions, and the poller's `awaiting_merge` advance.

**Out of scope**
- U5 (retire reviewer-PAT #1898 + `can_review`/`approve_pr` + `ensure_mergeable`) — follow-up
  cleanup; after U4 lands, the `ensure_mergeable` call is gone and that code is dead but harmless.
- The wgmesh-side judge/check/ruleset (U1–U3, done).
- Board/aging-KPI treatment of `awaiting_merge` — note it; tune later.

### Deferred to Follow-Up Work
- U5 reviewer-PAT retirement.
- A board-status mapping for `awaiting_merge` (Projects v2) so dashboards reflect "merging".

---

## Key Technical Decisions

- **KTD1 — `awaiting_merge` is a non-terminal, actionable stage.** `reviewed → awaiting_merge` is the
  new happy path (replacing `reviewed → merged`); `awaiting_merge → {merged, escalated, failed}`.
  It's in `ACTIONABLE_STAGES` so `claim_next` re-picks it to poll the PR. `merged` stays terminal.
- **KTD2 — Box enables auto-merge, never self-merges.** `apply_gate_side_effects`'s `merge` branch
  calls `client.enable_auto_merge(impl_pr)` and returns — no `ensure_mergeable`, no `box_ci`
  precondition, no `merge_pr`. The forge's required checks (`impl-judge` + build + status) are the
  gate.
- **KTD3 — Completion only on real merge.** The `awaiting_merge` advance reads the PR: **merged** →
  `transition(awaiting_merge → merged)` + close issue; **closed-unmerged** → escalate (needs-human);
  **open** → stay (no transition; claim cooldown re-polls) until a staleness bound, then escalate
  (a sustained judge FAIL or stuck check).
- **KTD4 — `enable_auto_merge` is mode-gated and GraphQL.** GitHub auto-merge is GraphQL-only
  (`enablePullRequestAutoMerge`, `mergeMethod: SQUASH`). The client has no GraphQL helper (all REST
  via `_write`/`_request`); add a minimal one. Respect the write gate: `shadow` → `DryRunResult`
  record; `spec-only` → `PermissionError`; `live` → the mutation (auth via `WGMESH_BOT_PAT`).
- **KTD5 — Idempotent enable.** Enabling auto-merge on a PR that already has it (or is already
  merged) must not raise — tolerate the "already enabled"/"clean status" GraphQL errors so a retry
  tick is safe (mirrors the merge_pr "tolerate already-merged" intent).

---

## High-Level Technical Design

```
reviewed  --(decide_gate == merge)-->  apply_gate_side_effects:
                                          client.enable_auto_merge(impl_pr)   [mode-gated]
                                        transition reviewed -> awaiting_merge   (NOT merged)
                                          │
   (forge: impl-judge PASS + build + status green -> GitHub auto-merges the PR)
                                          │
awaiting_merge  --(claim_next re-polls the PR)-->  advance:
        PR merged          -> transition awaiting_merge -> merged   (close issue)   ✓ real completion
        PR closed-unmerged -> escalate (needs-human)
        PR open & fresh     -> stay (cooldown re-poll)
        PR open & stale > N -> escalate (sustained judge FAIL / stuck check)

decide_gate == escalate (unchanged) -> add needs-human label
```

State transitions added: `reviewed → awaiting_merge`, `awaiting_merge → {merged, escalated, failed}`;
`awaiting_merge` added to `ACTIONABLE_STAGES`. `merged`/`escalated` stay terminal.

---

## Implementation Units

### U1. `client.enable_auto_merge` — GraphQL, mode-gated, idempotent

- **Goal:** Enable GitHub auto-merge (squash) on a PR; the forge merges it when required checks pass.
- **Requirements:** KTD4, KTD5.
- **Dependencies:** none.
- **Files:**
  - `pipeline/wgmesh_pipeline/github/client.py`
  - `pipeline/tests/test_github_client.py`
- **Approach:** Add a constant for the GraphQL endpoint and a small `_graphql(query, variables)`
  helper (mirrors `_request`: `session.post`, `WGMESH_BOT_PAT` bearer, `HTTP_TIMEOUT_SECONDS`,
  raise on transport/`errors`). Add `enable_auto_merge(pr_number, *, merge_method="SQUASH")`:
  mode-gate first (`shadow` → append a `DryRunResult(operation="enable_auto_merge")` and return;
  `spec-only` → `PermissionError`), then `get_pr` for the `node_id` and run the
  `enablePullRequestAutoMerge` mutation. Tolerate "already enabled" / "pull request is in clean
  status" / "not mergeable" GraphQL errors as success-ish (KTD5) — do not raise on a retry.
- **Patterns to follow:** `_write` (mode gate + `DryRunResult` + spec-only `PermissionError`),
  `merge_pr` (write shape), `_request` (auth + timeout + error wrap), the "tolerate already-merged"
  note on `merge_pr`.
- **Test scenarios:**
  - `mode=shadow` → records a `DryRunResult`, no network, returns dry-run.
  - `mode=spec-only` → raises `PermissionError`.
  - `mode=live` → posts the mutation with the PR's `node_id` + `SQUASH` (stub the session; assert
    the GraphQL body).
  - GraphQL returns an "already enabled" error → does NOT raise (idempotent).
  - GraphQL returns a real error (bad PR) → raises with detail.
  - missing `node_id` from `get_pr` → raises a clear error.
- **Verification:** unit tests green with a stubbed session; no real network.

### U2. Gate side-effect: enable auto-merge instead of self-merge

- **Goal:** On a `merge` decision, the box enables auto-merge and stops — no distinct-principal path.
- **Requirements:** KTD2.
- **Dependencies:** U1.
- **Files:**
  - `pipeline/wgmesh_pipeline/graph/nodes/gate.py`
  - `pipeline/tests/test_gate.py` (or wherever `apply_gate_side_effects` is tested)
- **Approach:** In `apply_gate_side_effects`, replace the entire `decision == "merge"` body
  (`box_ci` read, `ensure_mergeable`, readiness-escalate, `merge_pr`) with a guard for `impl_pr`
  then `client.enable_auto_merge(int(impl_pr))`. Remove the now-unused `ensure_mergeable`/`BoxCiResult`
  imports from this module. The `else` (escalate → `add_label("needs-human")`) is unchanged. Shadow
  mode is handled inside `enable_auto_merge` (KTD4), so drop the `mode != "shadow"` special-casing
  here.
- **Test scenarios:**
  - `decision == "merge"` with an `impl_pr` → calls `enable_auto_merge(impl_pr)`, does NOT call
    `merge_pr` or `ensure_mergeable`.
  - `decision == "merge"` with no `impl_pr` → raises (unchanged guard).
  - `decision == "escalate"` → adds `needs-human` (unchanged).
  - `mode=shadow` → `enable_auto_merge` dry-runs (no real call); no escalate.
  - No reference to `ensure_mergeable`/approval remains on the merge path.
- **Verification:** the merge path never reads approvals; a fake client records an
  `enable_auto_merge` call.

### U3. State machine: the `awaiting_merge` stage

- **Goal:** Add the non-terminal stage + its transitions so the box can park a PR mid-merge.
- **Requirements:** KTD1.
- **Dependencies:** none (can land before U4 wires it).
- **Files:**
  - `pipeline/wgmesh_pipeline/state/store.py`
  - `pipeline/tests/test_state.py`
- **Approach:** In `ALLOWED_TRANSITIONS`: change `reviewed` to `{awaiting_merge, escalated, failed}`
  and add `awaiting_merge: {merged, escalated, failed}`. Add `awaiting_merge` to `ACTIONABLE_STAGES`
  so `claim_next` re-polls it. `merged`/`escalated` stay terminal (empty sets). Keep
  `requeue_failed` and cooldown logic intact (a re-poll of `awaiting_merge` uses the same
  attempt/cooldown machinery).
- **Test scenarios:**
  - `transition(reviewed → awaiting_merge)` allowed; `reviewed → merged` now rejected (the box no
    longer jumps straight to merged).
  - `transition(awaiting_merge → merged)` allowed; `awaiting_merge → escalated` allowed.
  - `awaiting_merge → spec_ready` (or any non-listed) rejected.
  - `claim_next` returns an `awaiting_merge` issue (it is actionable).
  - `merged` remains terminal (no outgoing transition).
- **Verification:** transition table tests green; an `awaiting_merge` issue is claimable.

### U4. Poller: park on enable, complete on real merge

- **Goal:** Route the `merge` decision to `awaiting_merge`, and advance `awaiting_merge` only on the
  real PR outcome.
- **Requirements:** KTD3.
- **Dependencies:** U1, U2, U3.
- **Files:**
  - `pipeline/wgmesh_pipeline/poller.py`
  - `pipeline/tests/test_poller.py`
- **Approach:** In the `reviewed` handler, change the outcome of a `merge` decision from `merged` to
  `awaiting_merge` (transition `reviewed → awaiting_merge`; score the run as the enable, not a
  completion). Add an `awaiting_merge` stage handler: read the `impl_pr` via the client
  (`get_pr`/merge state) — **merged** → `transition(awaiting_merge → merged)` and close the issue
  (mirror the existing close-on-merge path); **closed & not merged** → escalate (`add_label
  needs-human`, transition `awaiting_merge → escalated`); **open** → no transition (return the issue
  unchanged so the cooldown re-polls), except when the PR has been open beyond a staleness bound
  (reuse the retry/age machinery) → escalate. Preserve the side-effect-before-terminal-transition
  discipline (don't record `merged` before confirming the PR merged).
- **Test scenarios:**
  - `reviewed` + `decision=merge` → issue goes to `awaiting_merge`, `enable_auto_merge` called, NOT
    `merged`.
  - `awaiting_merge` + PR merged → `merged` (terminal) + issue closed.
  - `awaiting_merge` + PR closed-unmerged → escalated + `needs-human`.
  - `awaiting_merge` + PR still open (fresh) → stays `awaiting_merge`, no transition.
  - `awaiting_merge` + PR open past the staleness bound → escalated (sustained judge FAIL).
  - `mode=shadow` → enable dry-runs; no real merge/close.
- **Verification:** a fake client/PR drives each branch; no issue is marked `merged` while its PR is
  open — assert the cardinal invariant directly.

---

## Risks & Dependencies

- **R1 — Phantom completion (the whole reason for this plan).** Marking `merged` on enable would be
  a false completion. Mitigation: `awaiting_merge` + complete-only-on-real-merge (KTD3, U4); the U4
  verification asserts no `merged` while the PR is open.
- **R2 — Stuck `awaiting_merge` churn.** A PR whose judge keeps FAILing sits `awaiting_merge` and is
  re-polled forever. Mitigation: the staleness-bound escalate (KTD3) hands it to `needs-human`; the
  existing attempt/cooldown backoff throttles re-polls.
- **R3 — `enable_auto_merge` on a repo without auto-merge enabled / without the ruleset.** wgmesh has
  `allow_auto_merge=true` and the `protect-main` ruleset (U3). If a target repo lacks them, the
  GraphQL mutation errors → handle as escalate, not a crash. Mitigation: KTD5 tolerant handling +
  U4's open/stale escalate.
- **R4 — GraphQL auth/endpoint.** New code path vs the REST `_request`. Mitigation: reuse
  `WGMESH_BOT_PAT` + `HTTP_TIMEOUT_SECONDS`; unit-test with a stubbed session.
- **Dependency:** U1–U3 done (wgmesh check + ruleset live). Deploy to the box via
  `update-pipeline-box` after merge; validate on the next box `fix:` PR.

## Verification (end-to-end)

1. Unit suites green (client, gate, state, poller).
2. Merge → `update-pipeline-box`.
3. Box journal: a box `fix:` PR reaches `reviewed → awaiting_merge`, `enable_auto_merge` logged, the
   PR shows GitHub auto-merge enabled; when `impl-judge`+build+status pass the forge merges and the
   next tick transitions the issue `awaiting_merge → merged` + closes it.
4. Negative: force a judge FAIL (a spec-violating diff) → PR stays open, issue stays `awaiting_merge`,
   no phantom `merged`; past the staleness bound it escalates to `needs-human`.
5. Then U5 retires the now-dead reviewer-PAT path.
