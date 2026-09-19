---
title: "feat: judge-gated automerge — DeepSeek CI check replaces distinct-principal approval"
type: feat
date: 2026-06-20
depth: deep
origin: none (merge-side of the non-goose autobox; convergence-stall layer 3)
---

# feat: judge-gated automerge (merge-side)

**Target repos:** **wgmesh** (`atvirokodosprendimai/wgmesh`, the seed product — judge check +
automerge live here) and **meta-repo** (`ai-pipeline-template` — the box stops self-merging).

## Summary

The non-goose autobox now produces real `fix:` PRs autonomously (live, GLM-5.2). But they
**don't merge** — at the box's `reviewed` stage the distinct-principal gate
(`forge/merge_gate.ensure_mergeable`) requires a non-author approval the box can't supply
(`WGMESH_REVIEWER_PAT` unset), so every PR goes `reviewed -> escalated` (confirmed live on #792).
This is convergence-stall **layer 3** — product-merge stays 0, aging KPI can't reach 0.

Operator decision: **forge automerge + a judge CI check** (not a PAT/approval). The merge gate
becomes an objective, fail-closed **DeepSeek** LLM-judge check on the PR; GitHub auto-merge merges
when all required checks (build/test + judge) pass. No reviewer identity, no 422, CI/CD-portable.
The "second principal" is an automated gate that can say NO — DeepSeek is a different model family
from the GLM-5.2 implementer, giving real independence cheaply.

## Problem Frame

- **Observed (live):** `advanced #792 reviewed -> escalated`; `ensure_mergeable` finds CI green +
  `mergeable=MERGEABLE` but `approvals=[]` → escalate.
- **Operator framing:** *"if we have automerge with test calling some judge that fails otherwise -
  then merge would not succeed"* — judge as a required CHECK, not an approval.
- **Goal:** an autonomous `fix:` PR with a green build and a passing fail-closed judge **auto-merges**
  in wgmesh, with no human/bot approval and no reviewer PAT. Product-merge > 0; aging KPI falls.

---

## Scope Boundaries

**In scope**
- wgmesh: a `impl-judge` CI check (DeepSeek, faithfulness + safety, fail-closed) + branch
  protection requiring it + GitHub auto-merge enabled.
- meta-repo box: at `reviewed`, enable auto-merge on the impl PR and stop self-merging; retire the
  distinct-principal/reviewer-PAT path.
- Retire the reviewer-PAT wiring (#1898) + `WGMESH_REVIEWER_PAT`.

**Out of scope**
- The executor (impl-side) — done and live.
- Goose retirement — separate follow-up.
- Re-enabling the OTHER disabled wgmesh lanes (spec-approve etc.) beyond what automerge needs.
- Porting the judge to non-GitHub CI — the design is portable but only GitHub is implemented now.

### Deferred to Follow-Up Work
- Push the judge verdict to Langfuse as a `score` (Mode B) for measurement/trend (observability,
  not gating). See `reference_langfuse_architecture`.
- A second judge lens (perf/repro) if faithfulness+safety proves insufficient.

---

## Key Technical Decisions

- **KTD1 — Judge is a required CI check, merge is forge automerge.** Not an approval. GitHub
  branch protection requires `impl-judge` (+ existing build/status checks); `gh pr merge --auto`
  merges when all green. Removes the PAT/approval/422 problem entirely.
- **KTD2 — DeepSeek judge, distinct from the implementer.** Implementer = GLM-5.2; judge =
  DeepSeek (via OpenRouter, metered, cheap). Different model family = genuine second opinion.
  Merge-gating is low-volume, so metered cost is negligible.
- **KTD3 — Fail-closed.** Judge errors, missing diff, missing spec, ambiguous verdict, or a
  malformed LLM response → **check FAILS (red)**, never neutral/skip. A skipped check that
  automerge treats as pass is the trap (the empty-`{{output}}` lesson).
- **KTD4 — Reuse the evaluator rubrics, run them synchronously in CI.** Lift the
  `impl_faithfulness` + `public_safety_pass` prompts from
  `pipeline/evals/setup_langfuse_evaluators.py` as the judge rubric. NOT the async Langfuse eval
  layer (wrong timing/role per `reference_langfuse_architecture`).
- **KTD5 — Box stops self-merging.** At the `reviewed` stage, the box enables auto-merge on the
  impl PR and transitions to a terminal "awaiting-merge" state instead of running
  `ensure_mergeable`'s distinct-principal merge. The forge owns the merge.
- **KTD6 — Retire the reviewer-PAT path.** Remove `ensure_mergeable`'s approval requirement usage
  on the merge path, the `WGMESH_REVIEWER_PAT` provision wiring (#1898), and `can_review`/
  `approve_pr` if unused elsewhere.

---

## High-Level Technical Design

```
box (langchain/GLM-5.2) implements → opens fix: PR in wgmesh + `gh pr merge --auto` → box stops
        │
        ▼  wgmesh GitHub Actions on the PR:
        ├─ build / Status Check / Code Quality   (existing)
        └─ impl-judge (NEW):
              fetch PR diff + specs/issue-N-spec.md
              DeepSeek judge: faithfulness(diff vs spec) + public-safety(no secrets/PII/revenue)
              fail-closed → check pass/fail
        │
        ▼  branch protection requires: build + Status + impl-judge
   all required checks green → GitHub auto-merge merges the PR.   any red → stays open (no merge).
```

Contrast with today: box runs `ensure_mergeable` (needs non-author approval) → escalate. New: box
enables automerge and steps away; an objective judge check decides.

---

## Implementation Units

### U1. wgmesh: `impl-judge` script (DeepSeek, fail-closed)

- **Goal:** Score an impl PR's diff against its spec for faithfulness + public-safety; exit
  non-zero on fail or any error.
- **Requirements:** KTD2, KTD3, KTD4.
- **Dependencies:** none.
- **Files (wgmesh):** `.github/scripts/impl_judge.py` (stdlib + one HTTPS call to OpenRouter/DeepSeek)
- **Approach:** Inputs (env/args): the unified diff, the spec text, the issue number. Build a judge
  prompt from the lifted `impl_faithfulness` + `public_safety_pass` rubrics. Call DeepSeek
  (OpenRouter, `OPENROUTER_API_KEY`/`DEEPSEEK_API_KEY` secret) requesting a structured verdict
  (`PASS`/`FAIL` + reasons). **Fail-closed:** missing diff/spec, HTTP error, unparseable response,
  or `FAIL` → exit 1 with the reason printed; only an explicit `PASS` → exit 0. Cap diff size
  (truncate with a marker) to bound tokens.
- **Patterns to follow:** the stdlib-only HTTPS pattern in `setup_langfuse_evaluators.py`
  (`urllib`, Basic/Bearer auth, fail-closed); the Cloudflare-1010 User-Agent lesson if OpenRouter
  is CF-fronted.
- **Test scenarios:**
  - Faithful diff + safe → PASS, exit 0.
  - Diff that ignores the spec → FAIL, exit 1, reason names the gap.
  - Diff leaking a secret/PII/revenue figure → FAIL (safety), exit 1.
  - Missing spec or empty diff → FAIL (fail-closed), exit 1.
  - HTTP error / unparseable LLM response → exit 1 (never pass-by-default).
  - Oversized diff → truncated with marker, still scored.
- **Verification:** unit tests with a stubbed LLM response (PASS/FAIL/garbage) prove the exit-code
  mapping and fail-closed behavior without a live call.

### U2. wgmesh: `impl-judge.yml` workflow (the check)

- **Goal:** Run the judge on every `fix:` PR and surface it as a required check.
- **Requirements:** KTD1, KTD3.
- **Dependencies:** U1.
- **Files (wgmesh):** `.github/workflows/impl-judge.yml`
- **Approach:** `on: pull_request` (opened/synchronize) filtered to `fix: Issue #` titles/branches.
  Steps: checkout, resolve the spec (`specs/issue-N-spec.md`, fetch its branch if not on the PR
  base — mirror `nongoose-shadow.yml`'s spec-finder), compute the PR diff (`git diff base...head`),
  run `impl_judge.py`. The job's pass/fail IS the check. Secret: `OPENROUTER_API_KEY`. `set -a`
  env-export discipline; quote inputs.
- **Test scenarios:** `Test expectation: none — declarative GHA workflow.` Validate via a draft PR
  post-merge (U6 verification).
- **Verification:** opening a `fix:` PR triggers `impl-judge`; a bad diff yields a red check.

### U3. wgmesh: branch protection + auto-merge

- **Goal:** Require the judge + build checks; let GitHub auto-merge merge when green.
- **Requirements:** KTD1.
- **Dependencies:** U2.
- **Files:** ops/config (gh API branch-protection update; enable repo auto-merge).
- **Approach:** Via `gh api` (or repo settings): require status checks `impl-judge`, the build
  check, `Status Check` on `main`; enable "Allow auto-merge". Keep admin override off the
  autonomous path. Document the exact `gh api` calls in the PR.
- **Test scenarios:** `Test expectation: none — repo configuration.` Verify a PR with a red
  `impl-judge` cannot merge; a green one auto-merges.
- **Verification:** branch protection lists `impl-judge` as required; auto-merge is enabled.

### U4. meta-repo box: enable automerge, stop self-merging

- **Goal:** At `reviewed`, the box enables auto-merge on the impl PR and steps away — no
  distinct-principal merge.
- **Requirements:** KTD5.
- **Dependencies:** U3 (so automerge has something to gate on).
- **Files (meta-repo):**
  - `pipeline/wgmesh_pipeline/poller.py` (the `reviewed` stage transition)
  - `pipeline/wgmesh_pipeline/graph/nodes/gate.py` / `forge/merge_gate.py` (drop the
    distinct-principal merge side-effect on the autonomous path)
  - `pipeline/wgmesh_pipeline/github/client.py` (an `enable_automerge(pr)` op)
  - tests
- **Approach:** Replace `apply_gate_side_effects`'s merge call with `client.enable_automerge(impl_pr)`
  (GitHub `enablePullRequestAutoMerge` GraphQL or `gh pr merge --auto`). Transition the issue to a
  terminal `awaiting-merge` state (not `merged`, not `escalated`) — the forge completes the merge
  later; an existing reconcile/close path (or a new one) marks it done when the PR merges. Keep the
  box's review node + box_ci as advisory signals if useful, but the AUTHORITATIVE gate is now the
  wgmesh checks.
- **Test scenarios:**
  - reviewed stage → calls `enable_automerge(impl_pr)`, transitions to awaiting-merge, does NOT
    call the distinct-principal merge.
  - enable_automerge failure → issue stays reviewed (retry next tick), surfaced loudly (no phantom
    merged state — preserve the existing false-completion guard).
  - a PR that later merges → reconciled to terminal done.
  - sanitise/safety still gates PR creation upstream (unchanged).
- **Verification:** box journal shows `reviewed -> awaiting-merge` + automerge enabled; the PR
  merges once wgmesh checks pass.

### U5. Retire the reviewer-PAT path

- **Goal:** Remove the now-dead distinct-principal/reviewer-PAT machinery.
- **Requirements:** KTD6.
- **Dependencies:** U4.
- **Files (meta-repo):** `forge/merge_gate.py` (or its callers), `config.py` (`reviewer_pat`),
  `github/client.py` (`can_review`/`approve_pr` if unused), `.github/workflows/provision-pipeline-box.yml`
  (remove `WGMESH_REVIEWER_PAT` wiring from #1898), tests.
- **Approach:** Delete the reviewer-PAT env threading + `approve_pr`/`can_review` if no longer
  referenced; simplify `ensure_mergeable` or remove it from the autonomous merge path. Leave a note
  that the merge gate moved to forge CI.
- **Test scenarios:** suite green after removal; no references to `WGMESH_REVIEWER_PAT` remain;
  the box has no approval path.
- **Verification:** grep clean; provision no longer writes `WGMESH_REVIEWER_PAT`.

---

## Risks & Dependencies

- **R1 — Fail-open judge = bad merges.** The single biggest risk: a judge that passes on
  error/ambiguity would auto-merge bad code. Mitigation: KTD3 fail-closed, tested explicitly
  (garbage/HTTP-error → exit 1). Required-check + automerge means a red judge simply blocks.
- **R2 — Branch protection gaps.** If `impl-judge` is NOT actually marked required, automerge
  merges without it. Mitigation: U3 verifies the required-checks list; a PR with a red judge must
  be un-mergeable in the verification.
- **R3 — Spec availability in CI.** The spec lives on `bot/spec-N` branches; the judge workflow
  must resolve it (reuse the `nongoose-shadow.yml` spec-finder). Missing spec → fail-closed (R1).
- **R4 — Two judges (box review node + CI judge) disagree.** The CI judge is authoritative for
  merge; the box review node becomes advisory. Don't let the box's escalate-on-review-finding
  block a PR the CI judge would pass — route the box to automerge-and-step-away (U4).
- **R5 — DeepSeek/OpenRouter availability.** Judge call fails → fail-closed → PR doesn't merge
  (blocks, doesn't break). Acceptable; surfaced as a red check.
- **Dependencies:** wgmesh secret `OPENROUTER_API_KEY`; GitHub auto-merge enabled on wgmesh; the
  impl-side executor (done, live).

## Open Questions (resolve during implementation)

- **box_ci's role post-cutover** — keep it as an advisory signal, or retire it in favor of the
  wgmesh GHA checks? Decide in U4 (lean: retire from the merge path, the forge checks gate).
- **Terminal state modeling** — add an `awaiting-merge` stage vs. reuse an existing one + a
  reconcile path that closes the issue when the PR merges. Decide in U4.

## Verification (end-to-end)

1. Unit suites green (judge script, box automerge path).
2. wgmesh: a `fix:` PR with a faithful diff → `impl-judge` green → **auto-merges**; a bad diff →
   `impl-judge` red → stays open.
3. Box journal: `reviewed -> awaiting-merge`, automerge enabled, no escalate.
4. Next pulse: `product_pr_merged > 0`; aged_open_items falls; the box's `fix:` PRs land
   autonomously end-to-end (spec → implement → judge → merge).
