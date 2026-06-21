---
title: "feat: re-arm stuck bot PRs whose required check never ran (merge-lane heal)"
date: 2026-06-21
type: feat
status: planned
depth: standard
target_repo: ai-pipeline-template (runs against meta + seed wgmesh)
---

# feat: Re-arm stuck bot PRs whose required check never ran (merge-lane heal)

## Summary

A class of bot PRs is permanently stuck: MERGEABLE, all produced checks green, not draft —
but blocked forever because a **required** status check (`impl-judge`) was never produced, so
it sits *permanently pending* (absent ≠ red). GitHub auto-merge waits for a check that will
never post; the box never enabled auto-merge on these (they predate the U4 wiring). Result on
2026-06-21: **0 autonomous product merges** despite judge gate, box auto-merge, and the
required-check ruleset all being live.

This plan adds a durable self-heal that detects these stuck PRs and re-arms them — enables
auto-merge **and** pushes a trivial commit to fire the `impl-judge` workflow — so the gate runs
and the box's product PRs auto-merge. It mirrors the existing `conflict-heal` machinery exactly
and runs cross-repo (meta + seed). Its first scheduled run drains the standing seed backlog
(#782–#793 et al).

## Problem Frame

Seed `protect-main` ruleset (id `12831947`, active) requires three checks: **`impl-judge`**,
`status-check`, `build-and-push`. The `impl-judge.yml` workflow first fired
**2026-06-20T21:32Z**. Bot PRs opened *before* that (e.g. `fix: Issue #779` = #782, opened
2026-06-19) never received a `pull_request` event for the judge → the `impl-judge` check is
**absent** on them. A required check that is absent is *permanently pending*, not failing — so:

- GitHub auto-merge can never complete (waits on a check that won't post).
- These PRs also show `autoMergeRequest: null` — the box that created them predated `gate.py`'s
  `enable_auto_merge` call (U4, #1919), so auto-merge was never even requested.

Both must be fixed for a PR to merge: the check must be produced **and** auto-merge must be
enabled. Posting the check alone leaves a green-but-idle PR; enabling auto-merge alone leaves a
PR waiting on an absent required check.

This is the same family as conflict-heal's root cause (a stuck bot PR that "fires no
`pull_request` workflows → the judge never runs → dead-ends") and the documented
required-check-skipped-blocks-merge gotcha. conflict-heal already rescues the **CONFLICTING**
subset (its force-push re-arms the judge as a side effect); this plan rescues the
**MERGEABLE-but-unjudged** subset it skips.

## Requirements

- **R1** — Detect bot PRs that are stuck on an absent required check: open, not draft,
  `mergeable == MERGEABLE`, bot-authored (`bot/` head branch, mirroring conflict-heal's scope
  guard), title `fix: Issue #…` (the judge's own applicability predicate), and the required
  `impl-judge` check is **absent** from the PR's check set.
- **R2** — Re-arm each such PR: (a) enable auto-merge (idempotent), (b) push a trivial commit to
  the PR head branch to fire `pull_request: synchronize`, producing the `impl-judge` check.
- **R3** — Never touch human PRs (non-`bot/` head branches) — hard scope guard, identical to
  conflict-heal R1/R4.
- **R4** — Idempotent and non-thrashing: a PR re-armed once is not re-pushed every cycle. Track
  per-PR re-arm attempts + cooldown; only re-arm again if the check is still absent after the
  cooldown. Escalate to a human (`needs-human` + comment) after N failed re-arms.
- **R5** — Cross-repo: run against both the meta-repo and the seed repo
  (`pulse_seed_product_repo` → `TARGET_REPO`), exactly as conflict-heal does.
- **R6** — Pure planner / impure executor split: the decision is a pure, unit-tested function;
  git/GitHub mutations live in shell + thin orchestrator, mirroring
  `selfheal/conflict.py` ↔ `company/scripts/conflict-heal/`.
- **R7** — Mode-gated writes: `shadow` → dry-run, `spec-only` → blocked, matching
  `gate.py`'s `enable_auto_merge` mode-gating and the sanitise write-gate.

## Scope Boundaries

**In scope:** detecting and re-arming MERGEABLE bot `fix:` PRs whose `impl-judge` required check
is absent; enabling auto-merge on them; cross-repo; escalation after N attempts; draining the
current backlog as the first run.

**Out of scope (true non-goals):**
- Changing the `protect-main` ruleset or which checks are required.
- Changing the judge logic / rubric (`impl_judge.py`).
- Conflict resolution — `conflict-heal` (#1930) owns CONFLICTING PRs.
- Any change to merge *policy* (still judge-gated, fail-closed, no reviewer PAT).

### Deferred to Follow-Up Work
- **spec-PR orphan (facet B).** The judge job is gated `if: startsWith(title,'fix: Issue #')`,
  so `spec:` PRs skip the job and the `impl-judge` required check reports *skipped*. Whether a
  skipped job satisfies or blocks the seed ruleset is an execution-time unknown (see Open
  Questions). If it blocks, the fix — emit a passing neutral `impl-judge` check for non-`fix:`
  PR types so the required context is always satisfiable — is a separate change to the judge
  workflow, tracked as follow-up. This plan targets the product-merge KPI (`fix:` PRs) only.

## Key Technical Decisions

- **KTD1 — Re-arm by trivial commit, not close→reopen.** Push an empty commit
  (`git commit --allow-empty`) to fire `pull_request: synchronize` (a listed judge trigger:
  `types: [opened, synchronize, reopened]`). Gentler than close→reopen (preserves PR state and
  history), and it is a *new* commit so it needs only a normal push — no force, unlike
  conflict-heal's `--force-with-lease` rebase. _(Confirmed against seed `impl-judge.yml`.)_
- **KTD2 — Re-arm must enable auto-merge too.** Because the standing backlog shows
  `autoMergeRequest: null`, the heal step calls `client.enable_auto_merge(pr)` (reusing the
  exact method `gate.py` uses) in addition to firing the check. Order: enable auto-merge first
  (idempotent, no-op if already set), then push the commit; once `impl-judge` + `build-and-push`
  + `status-check` are green, GitHub merges with no approval.
- **KTD3 — Sibling of conflict-heal, sharing its workflow.** Add a second pass to
  `conflict-heal.yml` that runs **after** the rebase pass: rebase handles CONFLICTING (and
  re-arms them as a side effect of force-push), then the re-arm pass handles the remaining
  MERGEABLE-but-unjudged PRs. One bot-PR-merge-lane-heal workflow, shared cron
  (`0 1,7,13,19`), shared escalation idiom, separate state files. Avoids a second overlapping
  cron and a second permissions surface.
- **KTD4 — "Required check absent" detection.** Reuse the check-runs API already wrapped in the
  client. Add a thin method returning the set of check **contexts present** on the PR head SHA;
  a PR is a re-arm candidate when the required `impl-judge` context is **not** in that set.
  (Distinct from `pr_checks_green`, which only inspects checks that *did* run and would wrongly
  call an unjudged PR "green".)
- **KTD5 — Required-check list is config, not hardcoded.** The required context to look for
  (`impl-judge`) is read from config/env so the planner stays host-neutral and the same code
  works if the required set changes.

## High-Level Technical Design

Merge-lane heal, per cycle, per repo (meta + seed):

```
list open PRs (gh, --repo TARGET_REPO)
  │
  ├─ PASS A  rebase  ──▶ conflict.py: CONFLICTING bot PRs → rebase.sh (--force-with-lease)
  │                       (force-push fires synchronize → judge re-arms as side effect)
  │
  └─ PASS B  re-arm  ──▶ rearm.py (pure): for each PR, candidate iff
                          open ∧ ¬draft ∧ MERGEABLE ∧ head startswith "bot/"
                          ∧ title startswith "fix: Issue #"
                          ∧ "impl-judge" ∉ present_check_contexts(headSha)
                          ∧ not in cooldown
                        decision = rearm | escalate(after N) | skip
                          │
                          ├─ rearm:    enable_auto_merge(pr)  then  rearm.sh(empty commit + push)
                          ├─ escalate: add needs-human + comment (after N failed attempts)
                          └─ skip:     already armed / cooling down / human PR
  │
  └─ write check-rearm-state-{meta,seed}.json (retry_tracker + cooldown), unless dry_run
```

Pass B is intentionally downstream of Pass A: a PR that Pass A rebased is no longer MERGEABLE-
unjudged-without-a-running-judge (its force-push already fired the judge), so Pass B skips it.

## Implementation Units

### U1. Pure re-arm planner

**Goal:** Decide, per PR, whether to re-arm, escalate, or skip — with zero side effects.
**Requirements:** R1, R3, R4, R6.
**Dependencies:** none.
**Files:**
- `pipeline/wgmesh_pipeline/selfheal/rearm.py` (new)
- `pipeline/tests/test_rearm.py` (new)
**Approach:** Mirror `selfheal/conflict.py`'s shape. Export
`plan_check_rearm(prs, present_contexts_by_pr, state, *, required_context, max_retries, cooldown_hours, now)`
returning an ordered list of actions (`kind="rearm" | "escalate" | "skip"`, pr number, head
branch, reason). Candidate predicate per R1. Reuse `selfheal/models.py` constants
(`MAX_RETRIES_BEFORE_ESCALATE`) and the `retry_tracker` cooldown idiom. `mergeable is None`
(GitHub still computing) → skip, never act (same as conflict.py).
**Patterns to follow:** `selfheal/conflict.py::plan_conflict_heal`; `selfheal/retry_policy.py`.
**Test scenarios:**
- MERGEABLE `fix:` bot PR with `impl-judge` absent, no prior attempts → `rearm`.
- Same PR with `impl-judge` present (any conclusion) → `skip` (already armed).
- `spec:` bot PR (title not `fix: Issue #`) → `skip` (out of judge predicate).
- Human PR (head not `bot/`) → `skip` (R3 scope guard), even if otherwise eligible.
- Draft / `CONFLICTING` / `mergeable is None` → `skip`.
- PR with prior attempt inside cooldown → `skip`; cooldown elapsed + still absent → `rearm`.
- PR at `max_retries` failed attempts → `escalate` exactly once (cooldown-guarded, no re-escalate).
- Empty input → empty action list.
- Determinism: same inputs → identical ordered output.

### U2. Client: present-check-contexts query (+ reuse enable_auto_merge)

**Goal:** Let the orchestrator learn which check contexts exist on a PR, to detect the absent
required one.
**Requirements:** R1, R2 (KTD2/KTD4).
**Dependencies:** none (parallel to U1).
**Files:**
- `pipeline/wgmesh_pipeline/github/client.py` (modify — add `list_pr_check_contexts`)
- `pipeline/wgmesh_pipeline/forge/protocol.py` (modify — add to Forge protocol if the planner
  path needs it; else orchestrator-only)
- `pipeline/tests/test_client.py` (modify) — or the existing client test module
**Approach:** Add `list_pr_check_contexts(pr_number) -> set[str]` returning the set of check-run
names (and, where present, commit-status contexts) on the PR head SHA, via the existing
`/commits/{sha}/check-runs` call already used by `pr_checks_green`. Do **not** alter
`pr_checks_green`. `enable_auto_merge` already exists (`client.py:322`) — reuse as-is.
**Patterns to follow:** `GitHubClient.pr_checks_green` (`client.py`), `get_pr_mergeable`
(`client.py:126`).
**Test scenarios:**
- Head SHA with check-runs `[Analyze, build-and-push, status-check]` → set excludes `impl-judge`.
- Head SHA that also has `impl-judge` → set includes it.
- No check-runs yet → empty set.
- Pagination: contexts spanning multiple API pages are all included.
- Network/HTTP error surfaces (no silent empty-set masking an absent check as "present").

### U3. Re-arm executor (shell)

**Goal:** Push a trivial commit to a bot PR's head branch to fire the judge.
**Requirements:** R2, R3, R7.
**Dependencies:** none (parallel to U1/U2).
**Files:**
- `company/scripts/check-rearm/rearm.sh` (new)
- `company/scripts/check-rearm/test-rearm.sh` (new)
**Approach:** Mirror `company/scripts/conflict-heal/rebase.sh`. Args `(repo, number, branch)`.
**Hard bot-branch guard** (refuse any head not `bot/`-prefixed) before any git write. Clone/
fetch the PR head, `git commit --allow-empty -m "chore: re-arm impl-judge (merge-lane heal)"`,
normal `git push` (new commit — no force). Emit a single `OUTCOME=<slug>` result line
(`rearmed` / `noop` / `error` / `refused-non-bot`) for the orchestrator to parse. Route writes
through the sanitise gate per R7.
**Patterns to follow:** `conflict-heal/rebase.sh` (guard + OUTCOME line + parse idiom).
**Test scenarios (shell harness):**
- `bot/impl-foo` branch → empty commit created, push invoked, `OUTCOME=rearmed`.
- Non-`bot/` branch → `OUTCOME=refused-non-bot`, **no git write**.
- Push failure (simulated) → `OUTCOME=error`, non-zero, no partial state.
**Test expectation:** behavioral shell test mirroring `test-rebase.sh`.

### U4. Orchestrator (cross-repo, stateful)

**Goal:** Run one re-arm cycle for a repo: list PRs → plan → enable auto-merge + execute →
escalate → persist state.
**Requirements:** R2, R4, R5, R7.
**Dependencies:** U1, U2, U3.
**Files:**
- `company/scripts/check-rearm/run.py` (new)
- `company/check-rearm-state-meta.json` (new, seed `{}`)
- `company/check-rearm-state-seed.json` (new, seed `{}`)
- `pipeline/tests/test_check_rearm_run.py` (new)
**Approach:** Mirror `company/scripts/conflict-heal/run.py`. `run_check_rearm(target_repo,
state, *, gh_run, gh_mutate, rearm_fn, enable_auto_merge_fn, list_contexts_fn, dry_run, now,
required_context, cooldown_hours)`. List open PRs via `gh pr list --repo TARGET_REPO`
(number + headRefName + mergeable + title + isDraft), fetch present contexts per candidate
(U2), call `plan_check_rearm` (U1). For each `rearm` action: call `enable_auto_merge` (KTD2),
then `rearm.sh` (U3); a successful re-arm resets/advances the PR's tracker entry; a failure
increments toward the cap. For each `escalate`: add `needs-human` + comment (reuse conflict-
heal's `_escalate`). `dry_run` makes zero mutations and skips the state write. Injected side-
effect callables keep the orchestrator unit-testable (no live GitHub in tests).
**Patterns to follow:** `conflict-heal/run.py::run_conflict_heal`, `_escalate`,
`normalize_mergeable`, `list_open_prs`.
**Test scenarios:**
- One eligible PR → `enable_auto_merge` called once **and** `rearm_fn` called once; tracker
  records the attempt.
- `enable_auto_merge` is called before `rearm_fn` (KTD2 ordering) — assert call order.
- Re-arm failure → tracker increments; at cap → escalate path fires, `needs-human` added.
- `dry_run=True` → zero mutations, state unchanged, intentions printed.
- Two repos run independently writing their own `-meta` / `-seed` state file.
- Idempotency: a PR already showing `impl-judge` present → planner skips → no
  `enable_auto_merge`, no push.
- A PR re-armed last cycle, still within cooldown → skipped this cycle.

### U5. Wire the re-arm pass into the workflow

**Goal:** Schedule the re-arm pass cross-repo, after the rebase pass, with the right
permissions; drain the backlog on first run.
**Requirements:** R5, R7.
**Dependencies:** U4.
**Files:**
- `.github/workflows/conflict-heal.yml` (modify — add Pass B step/job invoking
  `company/scripts/check-rearm/run.py` for meta and seed, after the rebase step) **or**
  `.github/workflows/check-rearm.yml` (new) if a separate workflow reads cleaner during review.
**Approach:** Extend `conflict-heal.yml` (already `contents: write`, `pull-requests: write`,
`issues: write`; cron `0 1,7,13,19`; App-token auth; `TARGET_REPO` per repo). Add a step that
runs the re-arm orchestrator for each repo after the rebase step, committing the
`check-rearm-state-*.json` updates the same way conflict-heal commits its state. Honor
`dry_run` input. Backlog drain needs no separate one-shot — a manual `workflow_dispatch`
immediately after merge runs Pass B over the standing PRs.
**Patterns to follow:** existing `conflict-heal.yml` job/steps, state-commit, and App-token
generation.
**Test scenarios:** `Test expectation: none — CI/workflow wiring`; validated by a
`workflow_dispatch` dry-run showing intended re-arms for the current backlog, then a live run.
**Verification:** dry-run dispatch lists the stuck `fix:` PRs as `rearm` intentions; live run
produces the `impl-judge` check on a previously-absent PR and the PR auto-merges once green.

## Open Questions

- **OQ1 (blocking the spec-PR follow-up, not this plan): does a skipped `impl-judge` job satisfy
  or block the seed required check?** The judge job is `if: startsWith(title,'fix: Issue #')`,
  so `spec:` PRs skip it. Verify empirically on an open seed `spec:` PR (e.g. #784): does the
  `impl-judge` required context show satisfied-by-skip or expected-and-pending? If pending →
  spec PRs are also permanently blocked and the follow-up (emit a passing neutral check for
  non-`fix:` PR types) is required for full convergence. **Resolve by observation before
  starting the follow-up; does not block U1–U5.**
- **OQ2 (execution-time): is `enable_auto_merge` sufficient on a repo where auto-merge may be
  disabled at the repo level?** If GitHub repo settings have auto-merge off, `enable_auto_merge`
  errors. Confirm auto-merge is enabled on both repos; if not, that is a one-time repo-settings
  prerequisite, surfaced at first live run rather than guessed here.

## Risks & Dependencies

- **Thrash risk** — re-pushing every cycle would spam CI and PR timelines. Mitigated by R4
  cooldown + tracker; U4 tests assert no re-push within cooldown and skip-when-present.
- **Wrong-PR write risk** — pushing to a human branch would be a serious breach. Mitigated by
  the double bot-branch guard (planner R3 + executor refuse-non-bot in U3), mirroring conflict-
  heal's proven guard.
- **Stale-context false negative** — if `list_pr_check_contexts` silently returned empty on
  error, every PR would look "absent" and get re-armed. U2 requires errors to surface, not mask.
- **Dependency:** reuses live `client.enable_auto_merge` (gate.py path) and the conflict-heal
  workflow/auth surface — no new secrets or identities.

## Sources & Research

- Live diagnosis (2026-06-21 pulse): seed ruleset `12831947` requires `impl-judge`; judge first
  ran 2026-06-20T21:32Z; backlog PRs #782–#793 show `impl-judge` absent + `autoMergeRequest:
  null`. Memory: `project_zero_autonomous_merges_judge_required_check_orphan`.
- `gate.py:97-114` — `apply_gate_side_effects` → `client.enable_auto_merge(impl_pr)`; ruleset
  gates merge on `impl-judge` + build + status; mode-gated; poller parks `awaiting_merge`.
- Sibling pattern: `selfheal/conflict.py`, `company/scripts/conflict-heal/{run.py,rebase.sh}`,
  `conflict-heal-state-{meta,seed}.json`, `.github/workflows/conflict-heal.yml`
  (docs/plans/2026-06-21-002-feat-conflict-heal-plan.md).
- Seed `impl-judge.yml`: `on.pull_request.types=[opened,synchronize,reopened]`, job
  `if: startsWith(title,'fix: Issue #')`.
- Related learnings: `feedback_backlog_predating_lane_is_orphaned`,
  `feedback_conflicting_pr_runs_no_workflows`, `feedback_required_check_path_filter_blocks_merge`.
