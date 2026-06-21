---
title: "feat: Autonomous conflict-heal for stuck bot PRs"
type: feat
date: 2026-06-21
depth: deep
status: ready
origin: solo (ce-plan, grounded in session recon + self-heal architecture map)
target_repos: ai-pipeline-template (meta) + atvirokodosprendimai/wgmesh (seed)
---

# feat: Autonomous conflict-heal for stuck bot PRs

## Summary

The autonomous pipeline opens bot PRs (`bot/spec-*`, `bot/impl-*`), then `main` moves
(another PR merges, touching a shared file like `public/index.html`), and the bot PR goes
`mergeable=CONFLICTING`. The pipeline has **no capability to rebase** a conflicting PR — the
only conflict path is `merge_pr()` in `company/scripts/pr-review-merge.sh`, which retries the
merge twice then escalates to a human. Worse, a CONFLICTING PR fires **no `pull_request`
workflows**, so the `Impl Judge` gate never even runs on it — the PR is fully dead-ended and
dwells forever, refilling the aged-open-items KPI. 13 of 24 open seed PRs are this exact mode.

This plan adds a **conflict-heal** capability: a pure planner (in the established `selfheal/`
decision layer) that detects CONFLICTING bot PRs and decides per-PR whether to rebase or
escalate, plus a dedicated scheduled workflow that executes the rebase on an ephemeral runner
(`git rebase origin/main` → `--force-with-lease` push on clean rebase; `git rebase --abort` →
escalate on a real content conflict). A clean rebase re-arms the PR's `pull_request` workflows
+ judge gate, letting the existing merge lane consume it. The capability is scoped to
**bot-authored branches only**, runs across **both repos**, and reuses the heal retry/cooldown/
escalate-at-2 semantics so a genuinely unresolvable conflict still reaches a human after two
honest attempts.

---

## Problem Frame

**Current state:** conflict = dead end.
- `merge_pr()` (`company/scripts/pr-review-merge.sh:406-464`): merge → 1 retry → `escalate "Merge failed after retry (possible conflict)"`. No rebase.
- `selfheal/` sweeps (`pipeline/wgmesh_pipeline/selfheal/sweeps.py`) heal stale triage/copilot/approved via label toggles — **no conflict sweep**.
- `pr-disposition.yml`'s `classify.sh` already classifies `conflict-low`/`conflict-high`, but the action is a **Phase 2 no-op placeholder** (`.github/workflows/pr-disposition.yml:171-172`).
- A CONFLICTING PR runs no `pull_request` workflows → `Impl Judge` never fires (see learning: conflicting PR runs no workflows).

**Desired state:** a conflicting bot PR is automatically rebased onto `main`; on success it re-enters
the merge lane; only a genuinely unresolvable conflict (or a now-empty PR whose content already
landed) reaches a human — after two bounded attempts, not on the first conflict.

**Scope boundary:** bot branches only (`bot/spec-*`, `bot/impl-*`); never human-authored PRs. No
content-level conflict resolution (no union-merges, no clever auto-fix) — plain rebase, escalate on
conflict.

---

## Requirements

- **R1** — Detect open PRs with `mergeable=CONFLICTING` whose head branch is bot-authored (`bot/`),
  in either repo.
- **R2** — For each, attempt `git rebase origin/main` on an ephemeral runner; on a clean rebase,
  `git push --force-with-lease` the rebased branch.
- **R3** — On a rebase that cannot auto-resolve (`git rebase` reports conflict), abort cleanly and
  escalate (add `needs-human`, comment the reason) — but only after the per-PR attempt count reaches
  the cap (2); below the cap, leave it for the next cycle under cooldown.
- **R4** — Never force-push a non-bot branch. Use `--force-with-lease`, never bare `--force`.
- **R5** — A clean rebase resets the PR's retry entry (a healthy PR that re-conflicts later starts
  fresh); only auto-resolve *failures* increment toward the escalate cap.
- **R6** — Detect a post-rebase **empty** PR (content already in `main`, the squash-merge-base case)
  and escalate/flag it for close rather than force-pushing an empty branch.
- **R7** — Planning is a pure decision (testable with `NoCallForge`); all git/forge writes happen in
  the workflow executor. Mirrors the `selfheal/` planning-vs-execution split.
- **R8** — Run across both repos (meta + seed) from one workflow, parameterized by target repo.
- **R9** — A `dry_run` mode prints intended rebases/escalations without mutating GitHub or state.

---

## High-Level Technical Design

### Decision flow (per CONFLICTING bot PR)

```
list open PRs (target repo)
  └─ for each PR:
        head branch startswith "bot/"?            ── no ──▶ skip (never touch human PRs)
        get_pr(n).mergeable                        ── null ─▶ skip this cycle (GitHub still computing)
        mergeable == "CONFLICTING"?                ── no ──▶ skip
        tracker[pr-n].cooldown_until > now?        ── yes ─▶ skip (cooling down)
        tracker[pr-n].retries >= 2?                ── yes ─▶ HealAction(escalate)  [needs-human + 72h cooldown]
        else                                       ──────▶ HealAction(conflict_rebase)
```

### Execution (workflow runner, per conflict_rebase action)

```
clone target repo (token with contents:write) ─▶ fetch PR head branch
git checkout <bot-branch>
git rebase origin/main
  ├─ clean ─▶ post-rebase diff vs origin/main empty? ─ yes ─▶ escalate "content already in main" (R6)
  │                                                  ─ no  ─▶ git push --force-with-lease ; reset tracker[pr-n] (R5)
  └─ conflict ─▶ git rebase --abort ─▶ increment tracker[pr-n].retries ; (escalate handled by planner next cycle at cap)
persist company/conflict-heal-state.json ─▶ commit
```

### State / cadence

- New scheduled workflow `conflict-heal.yml`, matrix over `[meta, seed]`, `concurrency: conflict-heal-<repo> / cancel-in-progress`.
- Reuses the heal **retry semantics** (cooldown, `MAX_RETRIES_BEFORE_ESCALATE=2`, `ESCALATE_COOLDOWN_HOURS`) via a small shared policy helper, but writes a **separate state file** (`company/conflict-heal-state.json`) to avoid commit contention with `Pipeline Health`'s byte-exact `pipeline-health-state.json` writes (KTD-3).

---

## Key Technical Decisions

- **KTD-1 — Planner in `selfheal/`, executor in the workflow.** The conflict decision is a pure
  function returning `HealAction`s; git/forge writes live in `conflict-heal.yml`. Mirrors the existing
  `selfheal/` contract (runner returns actions, performs no writes) so it's `NoCallForge`-unit-testable
  and reuses the established mental model. *(Alternative: do everything in bash in the workflow —
  rejected: untestable, diverges from the heal pattern.)*

- **KTD-2 — Rebase on an ephemeral GitHub Actions runner, not the box.** Clone → rebase →
  `--force-with-lease` push in a throwaway runner. No box-state risk; the runner dies clean; isolated
  failure surface. *(Alternative: SSH to the box and rebase there — rejected: pollutes the box working
  tree, couples heal to box availability.)*

- **KTD-3 — Separate state file `company/conflict-heal-state.json`, shared retry *logic*.** Reuse the
  cooldown/cap/escalate-at-2 semantics (extract a small pure helper) but a distinct file. `Pipeline
  Health` rewrites `pipeline-health-state.json` byte-exact every 30 min; a second writer would create
  JSON commit conflicts — ironic for a conflict-heal feature. Distinct file = no contention. *(Honors
  the operator's "reuse the retry-tracker" at the logic+schema level, not the physical file.)*

- **KTD-4 — `--force-with-lease`, bot branches only.** Existing `push_branch()` uses bare `--force`;
  the new path tightens to `--force-with-lease` so a concurrent push to the branch isn't clobbered, and
  hard-guards the branch prefix (`bot/`) so a human PR can never be force-pushed. *(Highest-risk vector;
  the guard is load-bearing.)*

- **KTD-5 — Plain `git rebase origin/main`; escalate on any conflict.** No content merging, no
  `-X ours/theirs`, no union drivers. A real conflict means a human decides. Keeps the capability
  safe and predictable. *(Operator-confirmed.)*

- **KTD-6 — Empty-after-rebase ⇒ escalate, don't push.** A PR whose content already merged (the
  squash-merge-base dup-content case that produces these conflicts) rebases to an empty diff. Pushing
  an empty branch is meaningless; flag it `needs-human` (likely close) instead. *(Covers the actual
  #744/#755 failure shape.)*

- **KTD-7 — Reuse the existing bot-push token.** The workflow authenticates with the same app token
  the pipeline already uses to push `bot/*` branches (the migration off the expired `PUSH_TOKEN`),
  ensuring `contents:write` on both repos. *(No new secret; verify scope covers seed + meta.)*

---

## Implementation Units

### U1. Conflict-heal planner (pure decision)

**Goal:** a pure function that, given the open-PR snapshot + retry tracker + now, returns the
`conflict_rebase` / `escalate` / skip decisions. No I/O.

**Requirements:** R1, R3, R5, R7.
**Dependencies:** none.
**Files:**
- `pipeline/wgmesh_pipeline/selfheal/conflict.py` (new) — `plan_conflict_heal(prs, tracker, now, cfg) -> ConflictHealPlan`.
- `pipeline/wgmesh_pipeline/selfheal/models.py` (modify) — add `HealAction` kind constants `conflict_rebase`, and a `ConflictHealPlan` result dataclass (`actions: tuple[HealAction, ...]`, `tracker: dict`).
- `pipeline/wgmesh_pipeline/selfheal/retry_policy.py` (new) — small pure helper `apply_retry_gate(entry, now, *, max_retries, escalate_cooldown_hours) -> Decision` extracting the cooldown→cap→escalate logic (`sweeps.py:108-127`), so conflict reuses it without duplicating. Leave existing sweeps untouched to protect the byte-exact parity test (consolidating stale sweeps onto this helper is deferred).

**Approach:** input is a list of PR dicts already carrying `number`, `headRefName`, `mergeable` (the
workflow fetches these; planner stays pure). Filter to `headRefName.startswith("bot/")` and
`mergeable == "CONFLICTING"`. Per PR, key `pr-<n>`: run `apply_retry_gate`; on `escalate` emit
`HealAction(kind="escalate", target="pr", add_label="needs-human", comment=...)` + set 72h cooldown;
otherwise emit `HealAction(kind="conflict_rebase", number=n, target="pr", reason=...)`. The planner does
**not** itself increment retries for a rebase attempt — the executor reports success/failure back and the
*next* cycle's tracker reflects it (R5: clean reset, failure increment); model this as the planner
consuming a tracker the executor updated. Treat `mergeable is None` as skip (not conflict).

**Patterns to follow:** `selfheal/sweeps.py::_sweep_stale` (cooldown/cap/escalate shape); `HealAction`
dataclass in `selfheal/models.py`; `selfheal/runner.py` planning-only docstring contract.

**Test scenarios** (`pipeline/tests/test_conflict_heal.py`, new):
- Happy: one CONFLICTING `bot/impl-7` PR, empty tracker → one `conflict_rebase` action for #7.
- Filter: CONFLICTING PR on a non-`bot/` branch → no action (R1/R4 guard at planning).
- Filter: `mergeable == "MERGEABLE"` and `mergeable is None` → no action (null = GitHub still computing).
- Cooldown: `pr-7` has `cooldown_until` in the future → skipped, no action.
- Cap: `pr-7` has `retries == 2` → `escalate` action (needs-human, 72h cooldown set), not rebase.
- Reset semantics: a `pr-7` entry with `retries == 1` + CONFLICTING → still emits `conflict_rebase`
  (below cap), tracker entry preserved for the executor to update.
- Multiple PRs mixed states → exactly the right action per PR; order stable.
- `dry_run` flag surfaced in plan (actions produced, marked intended) — planner is pure so dry_run is a
  field on the result the executor honors.

**Verification:** `pytest pipeline/tests/test_conflict_heal.py` green; planner imports nothing that does
I/O; `NoCallForge`-style test passes (planner never calls a forge).

---

### U2. Expose `mergeable` on the Forge protocol

**Goal:** a clean accessor for a PR's mergeable state so the executor (and tests) don't reach into raw
GitHub dicts, and the conflict signal is forge-agnostic.

**Requirements:** R1, R8.
**Dependencies:** none (parallel to U1).
**Files:**
- `pipeline/wgmesh_pipeline/forge/protocol.py` (modify) — add `get_pr_mergeable(number: int) -> str | None` to the protocol (values: `"CONFLICTING"`, `"MERGEABLE"`, `"UNKNOWN"`/`None`).
- `pipeline/wgmesh_pipeline/github/client.py` (modify) — implement by reading `mergeable`/`mergeable_state` from the existing `get_pr()` response; map GitHub's `mergeable: true/false/null` + `mergeable_state` to the tri-state. Null ⇒ `None` (not yet computed).
- `pipeline/wgmesh_pipeline/forge/quackback.py`, `pipeline/wgmesh_pipeline/forge/gitea.py` (modify) — implement or `NotImplemented`-stub to satisfy the conformance suite.
- `pipeline/tests/test_forge_protocol.py`, `pipeline/tests/test_github_client.py` (modify).

**Approach:** GitHub's REST `mergeable` is `null` until the server computes it after a push; the executor
must treat `None` as "skip this cycle, recompute next run" (do **not** infer not-conflicting from null).
Keep the mapping in the client so the planner sees a clean tri-state string. Mirror the conformance-test
pattern used for other protocol methods (`test_forge_protocol.py`).

**Patterns to follow:** existing `get_pr()` / `find_open_pr_number()` in `github/client.py`; the forge
conformance test style in `test_forge_protocol.py`.

**Test scenarios:**
- `mergeable: false` (+ `mergeable_state: "dirty"`) → `"CONFLICTING"`.
- `mergeable: true` (+ `clean`) → `"MERGEABLE"`.
- `mergeable: null` → `None` (recorded responses fixture).
- Conformance: every forge adapter implements/declares the method (parametrized conformance test passes).

**Verification:** `pytest pipeline/tests/test_forge_protocol.py pipeline/tests/test_github_client.py`
green; full suite green (no protocol-conformance regression).

---

### U3. Rebase executor script

**Goal:** the actual git mutation — rebase one bot branch onto `main`, force-with-lease on success,
abort+signal on conflict, detect empty-after-rebase.

**Requirements:** R2, R4, R6.
**Dependencies:** none (consumed by U4).
**Files:**
- `company/scripts/conflict-heal/rebase.sh` (new) — args: target repo, PR number, head branch. Emits a
  structured result line (`OUTCOME=rebased|conflict|empty|skipped REASON=...`) for U4 to parse.
- `pipeline/tests/test_conflict_heal_rebase.*` (new) — test at whatever level the repo already tests
  bash (subprocess-driven pytest if that pattern exists; otherwise a thin Python wrapper around the git
  steps that *is* unit-tested, with the `.sh` a trivial shim). Confirm the existing test idiom for
  `company/scripts/` during execution.

**Approach:** hard-guard `case "$BRANCH" in bot/*) ;; *) echo "OUTCOME=skipped REASON=non-bot-branch"; exit 0;; esac`
before any push. Shallow-clone or fetch the target repo with the bot-push token; `git fetch origin main`;
`git checkout "$BRANCH"`; `git rebase origin/main`. On non-zero rebase: `git rebase --abort`; emit
`OUTCOME=conflict`. On success: if `git diff --quiet origin/main` (no delta) emit `OUTCOME=empty` and do
**not** push (R6); else `git push --force-with-lease origin "$BRANCH"` and emit `OUTCOME=rebased`. Never
`--force`. Never operate on a non-`bot/` branch.

**Execution note:** Force-push safety is the load-bearing invariant — write the bot-branch guard test
first, and assert the script never reaches a push line for a non-bot branch.

**Patterns to follow:** git-over-token push in `github/client.py::push_branch` (force semantics, cwd
handling); SSH/git idiom in `.github/workflows/update-pipeline-box.yml`; audit-line style in
`company/scripts/pr-review-merge.sh`.

**Test scenarios:**
- Bot branch, clean rebase, real delta → `OUTCOME=rebased`, push invoked with `--force-with-lease`.
- Bot branch, rebase conflict → `git rebase --abort` invoked, `OUTCOME=conflict`, **no push**.
- Bot branch, rebase clean but empty diff vs main → `OUTCOME=empty`, **no push** (R6).
- Non-bot branch input → `OUTCOME=skipped`, **no git push reached** (R4 — assert the push code path is
  never entered).
- Push uses `--force-with-lease`, never bare `--force` (grep/assert on the invoked command).

**Verification:** unit tests green; manual `dry_run` invocation against a scratch bot branch rebases and
force-with-lease-pushes; a deliberately conflicting scratch branch aborts and reports `conflict`.

---

### U4. Conflict-heal workflow (executor + state)

**Goal:** schedule the capability across both repos, wire planner → rebase → escalate, persist state.

**Requirements:** R3, R6, R7, R8, R9.
**Dependencies:** U1, U2, U3.
**Files:**
- `.github/workflows/conflict-heal.yml` (new).
- `company/conflict-heal-state.json` (new, seeded `{"retry_tracker": {}}`).
- `company/scripts/conflict-heal/run.py` (new, optional thin orchestrator) — list PRs via forge, call
  `plan_conflict_heal` (U1), invoke `rebase.sh` (U3) per action, apply escalate actions
  (`gh pr edit --add-label needs-human` + comment), update + write the state file. Keeps the YAML thin
  and the orchestration unit-testable.

**Approach:** `on: schedule: cron` (e.g. every 2-3h, offset from `pr-disposition`'s `0 */6`) +
`workflow_dispatch` with a `dry_run` boolean. `strategy.matrix.repo: [meta, seed]` resolving
`TARGET_REPO`. `concurrency: { group: conflict-heal-${{ matrix.repo }}, cancel-in-progress: true }`.
Steps: resolve token (KTD-7) → `run.py` does the planner+executor loop → on `rebase` actions call
`rebase.sh`; map its `OUTCOME` back (`empty`/repeated `conflict` → escalate) → commit
`conflict-heal-state.json` if changed (pull-rebase-on-push to avoid the state file itself conflicting).
`dry_run` short-circuits all mutations and prints intended actions. Escalation reuses the
`needs-human` + comment shape from `pr-review-merge.sh::escalate`.

**Patterns to follow:** `pr-disposition.yml` (cron + `dry_run` input + per-PR loop + state-fingerprint
commit); matrix/secrets/`concurrency` shape from `auto-deploy-on-merge.yml` (this session); state-commit
idiom from the heal/supervisor-rank workflows.

**Test scenarios:**
- `run.py` orchestration (mock forge + stubbed `rebase.sh`): CONFLICTING bot PR → planner yields
  `conflict_rebase` → `rebase.sh` stub returns `rebased` → tracker entry reset, no escalation.
- `rebase.sh` returns `conflict`, tracker at `retries=1` → increment to 2 (escalation next cycle).
- `rebase.sh` returns `conflict`, planner already at cap → `escalate` action applied (needs-human label +
  comment issued exactly once).
- `rebase.sh` returns `empty` → escalate "content already in main" (R6), no push.
- `dry_run=true` → planner runs, **zero** `gh` mutations and **zero** state writes (assert).
- Both matrix repos resolve distinct `TARGET_REPO` and distinct state scope.
- State-file write is idempotent: unchanged tracker → no commit.

**Verification:** `actionlint` clean on `conflict-heal.yml`; `pytest pipeline/tests/` full suite green;
a `workflow_dispatch` `dry_run` run on the seed repo lists the real CONFLICTING bot PRs (#744, #755, …)
and prints intended rebases without mutating; a live run rebases one and the PR flips to `MERGEABLE` +
its `Impl Judge`/`pull_request` checks fire.

---

## System-Wide Impact

- **Merge lane**: rebased PRs re-trigger `pull_request` workflows + `Impl Judge` → the existing
  judge-gated auto-merge (#1919) can finally consume the backlog. Conflict-heal is the missing feeder.
- **KPIs**: drains the aged-open-items breach (13 stuck seed PRs) and stops it refilling; failed rebases
  surface as honest `needs-human` escalations, not silent dwell.
- **`pr-disposition.yml`**: its `conflict-low`/`conflict-high` Phase-2 placeholder is now superseded by
  this dedicated workflow — left as a no-op for now (see Deferred).
- **Both repos**: meta + seed bot PRs both covered.

---

## Risks & Mitigations

- **Force-push clobbers work** → `--force-with-lease` + hard `bot/` branch guard (KTD-4, U3 guard test).
  Highest-severity vector; the guard test is mandatory.
- **State-file commit contention** with `Pipeline Health` → separate `conflict-heal-state.json` (KTD-3) +
  pull-rebase-on-push for the state commit.
- **GitHub `mergeable: null` race** (false negatives) → treat null as skip, recompute next cron (U2/U4).
- **Rebase churn / thrash** → per-PR cooldown + `cancel-in-progress` concurrency; escalate at 2 honest
  failures.
- **Empty-after-rebase** (dup-content base) → detect + escalate, never push empty (KTD-6, R6).
- **Token scope** → KTD-7 reuses the existing bot-push app token; verify `contents:write` on **both**
  repos during U4 (a seed-only token would silently no-op meta, or vice-versa).
- **Rebase changes authorship/CI identity** → bot branches are bot-authored already; rebase preserves
  commits; force-with-lease push is by the same bot principal. No distinct-principal gate impact.

---

## Dependencies / Prerequisites

- Bot-push app token with `contents:write` on `ai-pipeline-template` and `atvirokodosprendimai/wgmesh`
  (the post-`PUSH_TOKEN` app token; confirm scope).
- Forge adapter in use is GitHub (`github/client.py`); quackback/gitea only need conformance stubs (U2).

---

## Scope Boundaries

**In scope:** detect + rebase + force-with-lease + escalate for CONFLICTING `bot/` PRs across both repos;
pure planner + executor workflow; reuse heal retry semantics.

### Deferred to Follow-Up Work
- Consolidate `selfheal/` stale sweeps onto the shared `retry_policy.py` helper (U1 introduces it but
  leaves existing sweeps untouched to protect the byte-exact parity test).
- Remove or redirect the `conflict-low`/`conflict-high` placeholder in `pr-disposition.yml` once
  conflict-heal is proven in production.
- Auto-**close** (not just escalate) an empty-after-rebase PR whose content already merged.
- A pulse/health staleness metric for "CONFLICTING bot PRs older than N hours" to measure the heal.

### Out of scope
- Content-level conflict resolution (union-merges, `-X ours/theirs`, AI conflict-fixing).
- Rebasing or force-pushing **human-authored** PRs — never.
- Changing the merge gate or judge logic.

---

## Open Questions (execution-time)

- Exact cron offset for `conflict-heal.yml` (2h vs 3h) — pick during U4 to avoid overlapping
  `pr-disposition`'s `0 */6`.
- Whether `run.py` orchestrator is warranted or the loop fits cleanly in YAML+`rebase.sh` — decide once
  U3's result-passing shape is concrete; the plan assumes `run.py` for testability.
- Confirm the bot-push token secret name + that its scope already spans both repos (vs needs a grant).

---

## Sources & Research

- Self-heal architecture map (this session): `selfheal/` planning-only contract, `HealAction` shape,
  retry-tracker semantics, forge accessors (`get_pr` returns raw `mergeable`), `merge_pr()` escalate,
  test fixtures (`NoCallForge`, byte-exact parity).
- `company/scripts/pr-review-merge.sh:406-464` (existing conflict→escalate).
- `.github/workflows/pr-disposition.yml:171-172` (conflict-low/high Phase-2 placeholder — prior art).
- Learnings: conflicting PR runs no `pull_request` workflows; don't hand-fix PRs (maintain the pipeline);
  box redeploy / merge≠deploy lag (sibling KTLO gap).
