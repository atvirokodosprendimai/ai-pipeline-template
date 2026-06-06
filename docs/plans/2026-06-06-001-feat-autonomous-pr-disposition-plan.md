# feat: Autonomous PR-Disposition Step

**Status:** active
**Date:** 2026-06-06
**Origin:** docs/brainstorms/2026-06-06-autonomous-pr-disposition-requirements.md
**Depth:** Deep
**Target repo:** ai-pipeline-template (governs its OWN meta-pipeline PR queue, not the seed repo)

---

## Summary

A recurring step that dispositions the open PR queue toward the STRATEGY.md goal automatically: tiered auto-merge (low-risk paths auto, high-risk escalate), reasoned-close stale, auto-rebase low-risk conflicts, escalate genuine-human-only. Reuses the existing `company/scripts/pr-review-merge.sh` review+merge engine rather than building a new merge path. Closes the operator-merge-gate safely — automation may merge operator PRs, but only low-risk ones that passed Copilot-CLEAN + CI-green + sanitise on the current head SHA.

Directive driving max-autonomy bias: *"the goal of ai pipeline that it would make these choices automatically to get closer to the goal."*

---

## Problem Frame

`pr_dwell_violations` is a KPI with no actor — two consecutive pulses showed the identical 34 dwelling PRs. Operator PRs rot because the pipeline is structurally forbidden from merging them (`APPROVED_AUTHORS` = bots only); stale PRs never get reasoned-closed; conflicting PRs never get rebased. The pipeline measures the dwell but never acts on it.

---

## Key Technical Decisions

- **KTD1 — Reuse, don't reinvent the merge engine.** `company/scripts/pr-review-merge.sh` already encodes Copilot-review polling, sanitise-on-escalate (SEC-2), `manual-only` skip, `needs-human` escalation, and merge. Extend its authority to operator PRs under a tiered path gate rather than writing a second merge path. (see origin: KTD merge authority)
- **KTD2 — Tiered path risk seeds from the existing PII-policy regex.** High-risk = `^docs/(outreach|customers)/`, `company/system-prompt.md`, plus auth/secrets/payments globs, stored in config (`pr_disposition_high_risk_paths`) so it's editable without code change. Low-risk = everything else (docs, `.github/workflows/`, `scripts/`, tests).
- **KTD3 — Hybrid classifier.** Bash decides the mechanical signals (CI state, `mergeable`, Copilot review state vs head SHA, labels, author, changed-file risk tier). One LLM sub-call (OpenRouter-curl pattern) decides only the semantic "stale/superseded vs still-wanted" judgment.
- **KTD4 — Auto-rebase is safe.** Low-risk conflicting PRs are rebased via Codex/git then re-enter the review path; the rebased head must still pass Copilot+CI before merge, so autonomy never bypasses the guardrail. High-risk conflicts escalate (no auto-touch of sensitive files).
- **KTD5 — Guardrails are non-negotiable.** Merge requires a CLEAN Copilot review **on the current head SHA** (a stale review does not authorize merge), CI green (not pending/skipped-as-proxy), sanitise pass. High-risk path → operator click, always.

---

## High-Level Technical Design

```
pr-disposition.yml (cron 6h + dispatch + dry_run)
        │
        ▼
  classify.sh  ──per open PR──▶  {class, risk_tier, reasons}
        │   mechanical: CI, mergeable, copilot-review@headSHA, labels, paths
        │   LLM sub-call: stale/superseded judgment only
        ▼
  ┌────────────┬──────────────┬───────────────┬──────────────┐
  ▼            ▼              ▼               ▼              ▼
MERGE-low   MERGE-high     STALE          CONFLICT-low    HUMAN-only
(auto via   (prepare +     (reasoned-     (auto-rebase    (needs-human
 pr-review- label ready-   close, goal-    via Codex →     + RAH bounty)
 merge.sh)  to-merge +     citing comment, re-enters
            escalate)      sanitise)       review)
                                           CONFLICT-high → escalate
        │
        ▼
  idempotency: act once per (PR#, headSHA, decision); 1 disposition/PR/run
  state/ledger: company/pr-disposition-state.json
```

---

## Implementation Units

### U1. High-risk path tiering + config
- **Goal:** classify a PR's changed files as high-risk or low-risk.
- **Files:** `scripts/pr-disposition/risk-tier.sh`, `scripts/pr-disposition/test-risk-tier.sh`, `.compound-engineering/config.local.yaml` (append `pr_disposition_high_risk_paths`)
- **Approach:** seed high-risk globs from `.githooks` / `pii-policy-check` regex (`^docs/(outreach|customers)/`, `company/system-prompt.md`) + auth/secret/payment globs; read overrides from config. Any changed file matching → PR is high-risk.
- **Patterns to follow:** the path regex in #822's `pii-policy-check.yml`; config-read pattern in `goal-sprint.yml` (python inline read).
- **Test scenarios:** changed-files all docs → low; one file under `docs/customers/` → high; `company/system-prompt.md` → high; empty file list → low (safe default = treat as low only if truly no sensitive path; otherwise high). `Covers` guardrail KTD5.

### U2. PR classifier (mechanical + LLM judgment)
- **Goal:** produce `{class, risk_tier, reasons[]}` per open PR.
- **Dependencies:** U1
- **Files:** `scripts/pr-disposition/classify.sh`, `company/pr-disposition-system-prompt.md` (LLM stale-judgment prompt), `scripts/pr-disposition/test-classify.sh`
- **Approach:** bash reads `gh pr view` (mergeable, statusCheckRollup, reviews, labels, author, files, headRefOid). Decision tree: CONFLICTING→conflict(tier); needs-human/manual-only label→skip/human; mergeable+CI-green+Copilot-CLEAN@headSHA→merge(tier); else if LLM judges superseded→stale; else→leave (in-flight). LLM sub-call uses OpenRouter-curl + sanitise gating (reuse goal-sprint pattern), invoked ONLY for the stale-vs-wanted call.
- **Patterns to follow:** `goal-sprint.yml` LLM step; `pr-review-merge.sh` review-state reads.
- **Test scenarios:** green+clean-review+low-path→merge-low; green+clean-review+high-path→merge-high; CONFLICTING+low→conflict-low; CONFLICTING+high→conflict-high; review older than headSHA→NOT merge (in-flight/re-review); needs-human label→human; LLM says superseded→stale; LLM says wanted→leave. `Covers` KTD3, KTD5.

### U3. Extend merge authority to operator PRs (tiered)
- **Goal:** allow automation to admin-merge operator PRs, low-risk only, under full guardrails.
- **Dependencies:** U1, U2
- **Files:** `company/scripts/pr-review-merge.sh` (extend author gate + add tiered path check before merge), `company/scripts/test-pr-review-merge.sh` (extend if exists, else create)
- **Approach:** add operator login to an allowlist used ONLY when `risk_tier=low` AND Copilot-CLEAN@headSHA AND CI-green AND sanitise-pass. High-risk operator PRs: never merge — label `ready-to-merge` + escalate one-click. Preserve all existing bot-PR behavior unchanged.
- **Execution note:** characterization-first — add coverage pinning current bot-PR merge behavior BEFORE extending the author gate (legacy 27KB script, high blast radius).
- **Test scenarios:** operator PR low-risk all-gates-pass→merged; operator PR high-risk→labeled ready-to-merge+escalated, NOT merged; operator PR low-risk but Copilot COMMENTED-not-CLEAN→NOT merged; existing bot-PR path unchanged (regression). `Covers` KTD1, KTD5.

### U4. Stale reasoned-close action
- **Goal:** close superseded PRs with a goal-citing reason (processed, not discarded).
- **Dependencies:** U2
- **Files:** `scripts/pr-disposition/close-stale.sh`, `scripts/pr-disposition/test-close-stale.sh`
- **Approach:** compose reason from classifier's `reasons[]` (why superseded + goal link), sanitise, `gh pr close --comment --delete-branch`. Append to ledger.
- **Test scenarios:** stale PR→closed with non-empty reason + branch deleted; sanitise-reject→no close, escalate; reason cites goal/supersession. `Covers` pr_processing_rate (reasoned-close=processed).

### U5. Auto-rebase low-risk conflicts
- **Goal:** resolve low-risk merge conflicts so the PR re-enters review; escalate high-risk.
- **Dependencies:** U1, U2
- **Files:** `scripts/pr-disposition/rebase.sh`, `scripts/pr-disposition/test-rebase.sh`
- **Approach:** low-risk conflict → dispatch Codex rebase (or `git rebase origin/main` + force-push-with-lease on the PR branch); on success the new head triggers fresh Copilot+CI (guardrail intact). On rebase failure or high-risk → label `needs-rebase` + escalate. Never auto-rebase high-risk paths.
- **Test scenarios:** low-risk conflict, clean rebase→pushed, PR re-opened-for-review (mock); rebase fails→needs-rebase label+escalate; high-risk conflict→escalate, no rebase attempt. `Covers` KTD4.

### U6. Orchestrator workflow
- **Goal:** run the disposition over the open queue on cadence, idempotently.
- **Dependencies:** U1-U5
- **Files:** `.github/workflows/pr-disposition.yml`
- **Approach:** `cron: 0 */6 * * *` + `workflow_dispatch(dry_run)`. App-token/PUSH_TOKEN (reuse goal-sprint token selection). For each open PR: classify→route to U3/U4/U5/escalate. Idempotency fingerprint = `PR#+headSHA+decision` stored in state; skip if already acted. One disposition per PR per run. `dry_run` prints intended actions, mutates nothing.
- **Test scenarios:** Test expectation: none for the YAML wiring itself; behavior covered by U1-U5 + U9 e2e. (workflow is orchestration glue)

### U7. State + ledger
- **Goal:** persist disposition decisions + idempotency fingerprints.
- **Files:** `company/pr-disposition-state.json`
- **Approach:** `{ "ledger": [], "acted_fingerprints": [] }`; immutable-append. sanitise before commit (LLM-derived reasons). Commit gated on material change (supervisor-rank sentinel pattern).
- **Test scenarios:** Test expectation: none — seed data file; mutation covered by U4/U6 tests.

### U8. Pulse wiring
- **Goal:** make the disposition step visible in the PR-processing KPI as the actor.
- **Dependencies:** U6, U7
- **Files:** `.compound-engineering/config.local.yaml` (note `pr_disposition_enabled`, source note for `pr_processing_rate`)
- **Approach:** config flag + comment; pulse already reads `pr_processing_rate`/`pr_dwell_violations` from meta-repo PR data — no new metric needed, the step simply moves the existing number.
- **Test scenarios:** Test expectation: none — config/doc only.

### U9. Offline e2e test harness
- **Goal:** prove the full classify→act routing + guardrails offline.
- **Dependencies:** U1-U7
- **Files:** `scripts/pr-disposition/test-disposition-e2e.sh`
- **Approach:** PATH-shim `gh` mock returning fixture PRs across every class; assert: merge-low merges, merge-high escalates (no merge), stale closes-with-reason, conflict-low rebases, conflict-high escalates, unreviewed→no merge, stale-Copilot-review→no merge, dry_run mutates nothing. Print `PASS N/N`, non-zero on any fail.
- **Test scenarios:** all guardrails KTD5; one scenario per class; idempotency (same fingerprint twice→second run no-ops).

---

## Scope Boundaries

**In scope:** the meta-pipeline repo's own open PR queue.

**Deferred to follow-up work:**
- Auto-rebase of HIGH-risk PRs (stays escalate).
- LLM-assisted PR *content* quality review (Copilot/ce-code-review owns that).

**Outside this product's identity:**
- The seed repo (wgmesh) queue — flows through the existing spec→impl→bot-merge chain, not this step.
- Generating new work — that's goal-sprint.

---

## Risks & Mitigation

- **R1 — Auto-merging a bad operator PR.** Mitigation: CLEAN Copilot review on current head SHA + CI green + sanitise + low-risk-path, ALL required. High-risk always escalates. (3 prior PII incidents are exactly this failure mode.)
- **R2 — Force-push rebase corrupts a PR.** Mitigation: `--force-with-lease`, low-risk only, rebased head re-enters full review before any merge.
- **R3 — Classifier mislabels wanted PR as stale.** Mitigation: LLM judgment is advisory for stale only; reasoned-close comment is reversible (reopen); never deletes work, branch-delete is recoverable from closed-PR.
- **R4 — Re-comment/re-act flood.** Mitigation: idempotency fingerprint `PR#+headSHA+decision`; one disposition/PR/run; respect existing labels.

---

## Success Criteria

- `pr_dwell_violations` trends down across pulses with zero manual action.
- 100% of closed PRs carry a goal-aligned reason.
- Zero unreviewed merges; zero high-risk-path auto-merges (assert in U9).
- Operator touch reduced to high-risk merge clicks + genuine human-only escalations.
