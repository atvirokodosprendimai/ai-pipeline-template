---
date: 2026-06-09
topic: customer-funnel-instrumentation
---

# Customer Funnel Instrumentation

## Summary

Instrument the customer funnel end-to-end — visit → checkout-click → paid, each event source-tagged — so the autonomous loop and pulse read a fresh-or-`UNKNOWN` customer-side signal instead of carrying "0 customers, unverified" forward. A scheduled synthetic transaction and per-stage liveness checks keep the funnel trustworthy before any real customer exists, and re-test the suspected Polar misconfiguration as a side effect.

---

## Problem Frame

The company is Day 83 in the Revenue stage with 0 *verified* paying customers, and the revenue side is its least-instrumented surface. `company/metrics.json` and `costs.json` have been stale since April; every pulse carries "0 customers" forward unverified because the paid-customer count comes from an HTML scrape of `chimney.beerpub.dev` rather than a live source. A Polar misconfiguration (5 org subscribers visible, but 0 attributed to cloudroof) was flagged 2026-05-26 and remains open — so it is currently unknown whether a customer *could even complete a payment*.

The result is a blind spot exactly where the strategy says value is decided: "converging on code without converging on revenue is theatre." The pipeline cannot improve a funnel it cannot see, and a carried-forward "0" is indistinguishable from a broken integration. This brief closes that blind spot with measurement, independent of whether demand turns out to exist.

---

## Key Decisions

- **Instrument the funnel; don't run a demand campaign.** The deliverable is observability of the customer path, not traffic. It produces the missing customer-side learnings regardless of the demand outcome.
- **Two-tier truth, reconciled in-repo.** Top-of-funnel + attribution come from the existing PostHog instrumentation; bottom-of-funnel truth comes from a Polar webhook. Both reconcile into a committed funnel-state artifact, so the revenue-critical signal stays ground-truth in the repo rather than living behind an external SPOF.
- **Full funnel + attribution over bottom-only.** Each event carries a source/channel tag. This pays a larger capture surface now so a future paid customer can be tied to the channel that produced them — the prerequisite that makes a later distribution arm honest.
- **The live funnel has three stages, not four.** cloudroof.eu sells a $5/mo founding-member tier through a direct Polar one-click checkout with no email capture, so the funnel is visit → checkout-click (CTA hand-off to Polar) → invoiced/paid. Instrumenting these three existing stages is in scope; adding an email-capture/waitlist stage is not.
- **Trustworthy from zero via heartbeat + liveness.** Because every stage reads 0 until a real customer arrives, a scheduled synthetic transaction proves the checkout path carries a payment end-to-end, and per-stage liveness assertions prove each capture point is wired. Together they distinguish "pipe is broken" from "nobody came."
- **Stale renders `UNKNOWN` and escalates loudly — never a carried-forward 0.** A stale or breached signal is the metrics equivalent of a swallowed error; it must announce, not pass silently. This extends the existing action-success KPI discipline to the revenue signal.
- **Counts and stage-health only in the committed artifact.** Amounts, customer identity, and secrets stay out of the public repo.

---

## Requirements

**Capture & attribution**
- R1. Emit a funnel event at each stage — visit (cloudroof.eu), checkout-click (the CTA hand-off to Polar), invoiced/paid — each carrying a source/channel tag.
- R2. Top-of-funnel events (visit, checkout-click) flow through the existing PostHog instrumentation; bottom-of-funnel truth (invoiced/paid) comes from a Polar webhook that replaces the `chimney` HTML scrape as the paid-customer source.

**Source of truth & freshness**
- R3. A committed funnel-state artifact reconciles the two tiers into per-stage counts that the loop and pulse read. It holds counts and stage-health only.
- R4. Every value in the artifact carries a last-verified timestamp; once past its TTL it renders `UNKNOWN`, never a carried-forward prior value.

**Trustworthy from zero**
- R5. Each capture point self-asserts liveness (reachable / receiving); silence beyond its threshold is a breach.
- R6. A scheduled synthetic transaction drives a real signup → checkout → invoice through Polar test-mode, proving the checkout path carries a payment end-to-end.
- R7. A breach — a failed heartbeat or a stale stage — opens a `fn:billing` issue and sets the affected stage to `UNKNOWN`, rather than reading 0 or passing silently.

**Consumption & operability**
- R8. The pulse's paid-customer line and the loop's customer-side read both source from the funnel-state artifact (fresh-or-`UNKNOWN`), replacing the stale carried-forward figure.
- R9. The funnel is operable by the autonomous loop via API on the steady-state path — capture, webhook ingest, synthetic run, and artifact refresh require no manual step.

**Repo boundary**
- R10. No secrets, PII, customer identity, or exact revenue figures are committed to the public repo; Polar API keys and the webhook signing secret live in the secrets store. Any new recurring spend remains subject to human approval.

---

## Key Flows

- F1. Real customer converts
  - **Trigger:** A visitor arrives at cloudroof.eu from a tagged source.
  - **Steps:** Visit and checkout-click emit to PostHog with the source tag; the invoiced/paid event arrives via the Polar webhook; reconciliation updates per-stage counts in the funnel-state artifact.
  - **Outcome:** The pulse's paid line reflects a fresh, source-attributed count.
  - **Covers:** R1, R2, R3, R8

- F2. Synthetic heartbeat and breach handling
  - **Trigger:** The scheduled synthetic transaction runs, or a liveness assertion evaluates.
  - **Steps:** On a successful synthetic run, the checkout stage is marked live with a fresh timestamp. On a failed run or a silent stage, the stage flips to `UNKNOWN` and a `fn:billing` issue opens.
  - **Outcome:** A green funnel means "wired and able to take payment"; an all-zero funnel with a green heartbeat means "nobody came," not "broken."
  - **Covers:** R5, R6, R7

---

## Acceptance Examples

- AE1. **Covers R4, R7.** Given the checkout stage last verified 3 days ago with a 24h TTL, when the pulse reads the funnel, then checkout renders `UNKNOWN` (not its prior value) and the breach has opened a `fn:billing` issue.
- AE2. **Covers R6.** Given the first synthetic transaction runs against Polar test-mode, when it cannot complete signup → checkout → invoice, then the run fails loudly and surfaces the Polar misconfiguration as a tracked `fn:billing` defect.
- AE3. **Covers R1, R3.** Given a real visit or checkout-click arrives tagged from a channel, when reconciliation runs, then that stage's count increments with its source tag and no amount or customer identity is written to the committed artifact.

---

## Success Criteria

- The pulse's paid-customer line is sourced from a live Polar webhook with a visible last-verified timestamp, not the `chimney` scrape.
- The funnel-state artifact is always either fresh or explicitly `UNKNOWN` — no stale value is ever presented as current.
- A passing synthetic transaction demonstrates an end-to-end payment through test-mode; its first run either confirms the Polar misconfiguration is resolved or files it as a tracked defect.
- After one real or synthetic conversion, visit → signup → checkout → paid is traceable with source attribution intact.

---

## Scope Boundaries

**Deferred for later**
- Distribution arm (Mixpost) — gated behind a working, attributed funnel; it amplifies a funnel that converts, and is dishonest before attribution exists.
- Driving traffic, demand campaigns, and choosing/“demand-testing” the 2nd seed product — this brief measures the funnel; it does not feed it.

**Outside this product's identity**
- This is revenue-measurement infrastructure, not a growth/marketing engine. It does not decide what to sell or to whom; it makes whatever happens in the funnel observable.

---

## Dependencies / Assumptions

- Polar provides a full sandbox for R6 — `sandbox.polar.sh` / `sandbox-api.polar.sh`, a separate access token, SDK support via `server: 'sandbox'` (Go/Python/TypeScript/PHP), and the Stripe test card `4242 4242 4242 4242`. It exercises the complete checkout funnel. Confirmed; R6 is feasible as written.
- cloudroof.eu sells a $5/mo founding-member tier via a direct Polar one-click checkout (`buy.polar.sh/...`) with no email capture. Confirmed; the funnel is three-stage.
- The existing PostHog instrumentation (`company/scripts/posthog-emit.sh`) can carry the new funnel events and source tags.
- `chimney.beerpub.dev` HTML scrape is the current paid-customer source being replaced.

---

## Outstanding Questions

**Resolve before planning**
- None. Both prior blockers (cloudroof funnel shape, Polar sandbox availability) were resolved during the brainstorm — see Dependencies / Assumptions.

**Deferred to planning**
- TTL per stage and synthetic-transaction cadence.
- The reconciliation rule for aligning a visitor identity across PostHog (top) and Polar (bottom).
- The funnel-state artifact's location and counts-only field schema.
- Whether cloudroof.eu's checkout-click CTA already emits a distinct PostHog event or must be added.

---

## Sources / Research

- `STRATEGY.md` — "Customer Factory / Revenue surface" track (cloudroof.eu, chimney dashboard, Polar tiers); key metrics: paid customers via Polar, cycle-time-to-revenue `null` until ≥1 customer.
- `.compound-engineering/config.local.yaml` — `pulse_payments_source: polar`; `paid_customers=chimney-html` scrape "until Polar webhook integration"; action-success KPI (every autonomous action must succeed).
- `company/scripts/posthog-emit.sh` — existing server-side PostHog instrumentation.
- `scripts/pr-disposition/risk-tier.sh` — Polar/billing already classified as a high-risk path.
- `docs/ideation/2026-06-09-open-ideation.md` — origin (idea #7); the `UNKNOWN`/escalation contract is the lineage of ideation survivor #3 (metrics freshness + sentinel).
- Pulse `docs/pulse-reports/2026-06-09_07-10.md` — Polar misconfig (5 org subs vs 0 cloudroof) flagged 2026-05-26; Day 83, 0 verified customers; metrics stale since April.
