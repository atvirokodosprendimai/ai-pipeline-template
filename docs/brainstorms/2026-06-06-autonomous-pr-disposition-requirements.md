# Autonomous PR-Disposition Step — Requirements

**Date:** 2026-06-06
**Status:** ready for planning
**Sibling of:** goal-sprint step (`.github/workflows/goal-sprint.yml`)

## Problem

Pulses repeatedly show PRs dwelling. Root cause is structural, not technical: the autonomous pipeline is forbidden from processing operator-authored PRs (`APPROVED_AUTHORS` = bots only, 1-approval ruleset + self-approval ban), stale PRs never get reasoned-closed, and conflicting PRs never get rebased. The `pr_dwell_violations` KPI is a number with no actor — flagging it changes nothing. Two consecutive pulses showed the identical 34 dwelling PRs.

## Goal

A recurring step that **dispositions the open PR queue toward the STRATEGY.md goal automatically**, so PRs reach a goal-aligned terminal state without operator babysitting. Directly drives the `pr_processing_rate` / `pr_dwell_violations` KPI by *acting*, not measuring.

## Core behavior

For each open PR, classify and act:

| Class | Signal | Action |
|---|---|---|
| **Mergeable + goal-aligned** | CI green, no conflicts, Copilot review requested+CLEAN, sanitise pass | **Tiered merge** (see authority) |
| **Stale / superseded** | target already on main, or area rewritten since, or obsolete vs goal | **reasoned-close** (comment cites why + goal) |
| **Conflicting** | mergeable=CONFLICTING | dispatch **rebase** (Codex) or label `needs-rebase` |
| **Genuine human-only** | needs physical presence / wet-sig / irreversible-no-undo | **escalate**: `needs-human` + RAH bounty per autonomy ladder |

Reasoned-close counts as PROCESSED (per PR-processing KPI). Bulk-close with no reason is forbidden.

## Merge authority — TIERED (decided)

- **Low-risk paths** (docs, `.github/workflows/`, `scripts/`, tests, `company/` non-secret): **auto admin-merge** after ALL of: Copilot review CLEAN, CI green, sanitise pass, no conflict.
- **High-risk paths** (auth, secrets, payments, customer/outreach data, `company/system-prompt.md`, anything matching the PII-policy paths): **prepare only** — review + gate + label `ready-to-merge` + escalate for one operator click. Never auto-merged.
- Path risk-tier list lives in config, editable without code change.

This closes the operator-merge-gate **safely**: automation may admin-merge operator PRs, but only low-risk ones that passed every gate.

## Hard guardrails (non-negotiable)

1. **Never merge unreviewed.** Merge requires a CLEAN Copilot review on the current head SHA. (3 prior PII incidents came from `--admin`-before-Copilot.)
2. **Sanitise gate** on any content the step publishes/commits (`company/scripts/sanitise.sh`).
3. **CI must be green** (not pending, not skipped-as-proxy) before merge.
4. **Re-review on new commits**: a stale Copilot review (older than head SHA) does not authorize merge.
5. High-risk path → operator click, always.

## Anti-flood

- Idempotent per PR per head-SHA: act once, don't re-comment/re-review the same unchanged PR each run (fingerprint on PR#+headSHA+decision).
- One disposition per PR per run.
- Respect existing `needs-human` / `ready-to-merge` labels (don't churn).

## Success criteria

- `pr_dwell_violations` trends down across pulses without manual intervention.
- Every closed PR carries a goal-aligned reason (reasoned-close rate = 100%).
- Zero unreviewed merges; zero high-risk-path auto-merges.
- Operator touch reduced to: high-risk merge clicks + genuine human-only escalations.

## Out of scope

- Generating new work (that's goal-sprint).
- Reviewing PR *content* quality (that's Copilot / ce-code-review).
- The seed repo wgmesh (this step governs the meta-pipeline repo's own queue; seed-repo PRs flow through the existing spec→impl→bot-merge chain).

## Open questions (for planning)

- Cadence: every N hours vs daily? (lean: every 6h, matches observation-loop)
- Rebase: in-step (git rebase + push) vs dispatch Codex vs just-label? (lean: label `needs-rebase` + dispatch Codex for low-risk, label-only for high-risk)
- Engine: pure-bash classifier vs LLM-assisted classification for the stale/superseded judgment (lean: bash for mechanical signals, LLM only for the "superseded vs still-wanted" call).
