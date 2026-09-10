# Pipeline Roadmap — 2026-09-10

> Supersedes [2026-06-23-lang-triad-roadmap.md](2026-06-23-lang-triad-roadmap.md) as the
> current plan. Ladders to the three tracks in [STRATEGY.md](../../STRATEGY.md) and uses
> the axes indexed in [docs/taxonomy.md](../taxonomy.md).

## Strategy context

**Where the company is:** funnel **Stage 3 — Reachable**, entered **2026-03-18** (176 days).
Last committed assessment: **2026-06-22**, run #284.

| Milestone | Target | Status |
|---|---|---|
| 2nd seed product spec'd, entering convergence engine | 2026-06-14 | **overdue 88 days** |
| 4 customers ($10K ARR run-rate path) | 2026-08-31 | **overdue 10 days** |

**Last known customer truth** (2026-06-22): 5 paying subscribers, but **0 on all three cloudroof
seed products** — revenue flows from an unrelated product line.

**Hard constraint — frugality is survival.** Any new recurring cost needs human approval.

## The decisive context: the pipeline is off ON PURPOSE

Observable today: **45 of 62 workflows are `disabled_manually`**, including the whole merge and
build lane (*Heartbeat PR Auto-Merge*, *Bot PR Review and Merge*, *Supervisor Rank*, *Spec Merged
— Trigger Build*, *Copilot Issue Triage*, *Conflict Heal*, *PR Disposition*); the producers
(*Observation Loop*, *Pipeline Health*) are still `active` and report `success` daily; **455 pull
requests are open** (363 `pipeline-health/`, 74 `loop/`, 4 `conflict-heal/`, 3 `audit/`, 11
other); and `company/loop-state.json` has not changed since **2026-06-22**.

**This is not a break, and it is not unexplained.** The 2026-06-22 disablement was a deliberate,
operator-ordered, fail-closed **kill switch**. The autonomous box was speccing, building and
merging GTM/marketing work — cold outreach copy, comparison pages, a 5-email drip, a referral
system — with **no founder approval gate**, polluting the product `main` with features nobody
accepted at real token cost. Per plan-004: *"The box stays OFF until this gate is live and
shadow-proven."* Project memory recorded the same conclusion on 2026-08-29: the disable is
**correct behavior**, and the real debt is the **unexecuted plan-004 + the collateral PR pile**.

> **Therefore: do not re-enable the merge lane as a fix.** With no accept-gate live, re-enabling
> restores exactly the behavior the operator shut down. Any roadmap that opens with "restore the
> merge path" is prescribing the original harm.

The producers keep running and keep opening PRs that cannot merge. That backlog is **collateral**,
not backlog — it is the kill switch working.

## Where plan-004 actually stands (verified 2026-09-10)

`docs/plans/2026-06-22-004-feat-accept-gate-cleanup-reenable-plan.md` is the recovery path.
Eleven weeks on, most of it is unexecuted:

| Unit | Scope | Status |
|---|---|---|
| U1 | Approval accessor on Forge Protocol + GitHub client | **implemented — uncommitted** |
| U2 | Fail-closed gate at the poller `triaged → specced` chokepoint | **implemented — uncommitted** |
| U3 | Both-Surface coverage (wgmesh + cloudroof-eu instance) | partial — `ACCEPT_GATE_LIVE` in allowlist + box-config; cloudroof instance env unverified |
| U4 | Revert GTM Tier A+B off wgmesh `main` | **not done** (wgmesh repo) |
| U5 | Revert Tier C referral — unwire daemon first, build-breaking | **not done** (wgmesh repo) |
| U6 | Reconcile capabilities + confirm green `main` | **not done** (wgmesh repo) |
| U7 | Shadow-prove the gate blocks unapproved work | **not started** |
| U8 | Flip live + re-enable Actions, verified, with rollback | **not started** |
| U9 | Re-enable runbook (`docs/runbooks/accept-gate-reenable.md`) | **not written** — file absent |

U1/U2 exist only as working-tree edits; `pipeline/tests/` runs **98 passed** with them in place.
Uncommitted, they gate nothing and are one `git checkout` from being lost.

## Roadmap (Now / Next / Later)

| Stage | Initiative | Outcome | Metric | Notes |
|---|---|---|---|---|
| **Now** | **P0 — Land the accept-gate (U1–U3)** | Gate exists on `main`; dependency for every later step | Gate tests green on `main`; `get_decision_status` on both forges | Unblocked, code-complete, 98 tests green. Shipped 2026-09-10 |
| **Now** | **P0 — Decide the PR pile (455)** | Recurring cost and visual noise stop growing | Open PRs 455 → bounded | Collateral of a working kill switch, not backlog. Close-with-reason vs keep vs pause producers |
| **Now** | **P1 — U9 re-enable runbook** | The re-enable sequence is repeatable and rollback unambiguous | `docs/runbooks/accept-gate-reenable.md` exists | Doc-only, no operator dependency, unblocks U7/U8 |
| **Next** | **P1 — U7 shadow-prove the gate** | Evidence the gate blocks unapproved work before it enforces | Journal shows ≥1 `would_block`; zero unapproved Issues reach `specced` | Box already `CONTROL_LOOP_MODE=shadow`, `ACCEPT_GATE_LIVE=false`. Needs U2 merged |
| **Next** | **P1 — U4/U5/U6 clean GTM off wgmesh `main`** | Loop stops grounding on unrequested GTM | `pkg/nurture`, `pkg/promo`, `pkg/analytics` imports = 0; `go build`/`go vet` green | **wgmesh repo.** `pkg/referral` is daemon-wired — unwire before revert |
| **Next** | **P1 — D2 revenue attribution gap** | Revenue attributable to a seed product | cloudroof subscribers 0 → ≥1 | Unanswered since 2026-06-22 |
| **Next** | **P2 — U8 flip live + staged Actions re-enable** | Pipeline back online, proven | Approved Issue builds end-to-end; unapproved blocked; one-step rollback | Operator action. Gate-triggering workflows must fire from a PAT/user actor |
| **Later** | **P2 — Cost governance T1–T5** | Bounded pipeline spend | Per-stage cost in Langfuse | ADR accepted 2026-08-30, not started |
| **Later** | **P3 — Revenue milestones toward MSC** | 42 customers / $10K ARR | Paid customers | STRATEGY 2027-05-03 |

### Hypotheses

**P0 — Land the gate.** We believe merging U1/U2 moves the recovery path further than any other
single action, because it is the unblocked dependency for U7 and every step after it, and the work
is already code-complete and green. *Falsified if* the gate is hollow — green in unit tests but
inert against a live issue. Mitigation is U7 shadow-proofing, per plan-004's own high risk:
"Hollow-green gate".

**P0 — Decide the PR pile.** We believe the 455 PRs are pure cost with no signal value, because
nothing consumes them — anything they carried would have reached `main` before merging stopped.
*Falsified if* a consumer reads the open PRs directly.

## Sequencing

```
land gate (U1-U3)  ---> U7 shadow-prove ---> U8 flip live + re-enable   [operator]
                   ---> U9 runbook
wgmesh GTM cleanup (U4-U6) ---> U7 (loop must not ground on GTM)
PR pile disposition (independent)
```

U8 is strictly last: it is the only step that restores autonomous writes to product `main`.

## Risks & dependencies

| # | Risk / dependency | Mitigation / status |
|---|---|---|
| R1 | **Re-enabling before the gate is live** restores the original harm | Plan-004 U8 ordering + single-flag rollback. The kill switch is a **feature** |
| R2 | **Hollow-green gate** — green in tests, inert live (plan-004: high) | U7 shadow proof before any trust |
| R3 | **Fail-open on read error** — exception resolving to "approved" (plan-004: high) | Implemented: `_accept_gate_decision` denies on exception; explicit error-path tests |
| R4 | **Loop re-proposes reverted GTM** | KTD5 `Revert "<title>"` convention + U6 capability reconcile |
| R5 | **Actions re-enable fails silently** — App-token workflows never fire; missing check reads PENDING not RED | KTD6 actor verification; deliberate ordering |
| R6 | `loop-state.json` frozen 11 weeks | Every plan built on funnel/blocker data inherits the staleness |
| R7 | `docs/runbooks/accept-gate-reenable.md` absent | U9 |

## Decision points (human)

**D1 — Proceed with plan-004, or change the destination?**

1. **Execute plan-004** (recommended) — finish the gate, clean GTM, shadow-prove, then staged re-enable.
2. Keep the pipeline off indefinitely; treat the autonomous build lane as retired.
3. Retire the autonomous pipeline entirely and delete the producers, so no PRs accumulate.

**D2 — Is the revenue attribution gap real?** 5 subscribers, 0 on seed products. Configuration
error, or genuinely separate product lines?

**D3 — What is the disposition of the 455 open PRs?** Close with reason (cheapest, loses nothing),
keep as an audit trail, or leave and pause the producers. Note the producers cannot be paused
without stopping Observation Loop, which is `active` and is the only current source of company
signal.

