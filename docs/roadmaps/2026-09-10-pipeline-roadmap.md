---
name: ai-pipeline-template Pipeline Roadmap
last_updated: "2026-09-10"
status: active
horizon: Now / Next / Later
owner: pipeline
---

# Pipeline Roadmap

**Horizon:** Now / Next / Later  ·  **Owner:** pipeline  ·  **Updated:** 2026-09-10

The roadmap ladders to [STRATEGY.md](../../STRATEGY.md) tracks and the open debt ledger.
Filter all PR metrics by `surface:product` + `surface:service` labels and by repo
(`atvirokodosprendimai/wgmesh` for product; `atvirokodosprendimai/cloudroof-eu` for service).
Meta work (`surface:meta`) does not count toward convergence.

Funnel stage status (from [system-prompt.md](../../company/system-prompt.md)):
- **Achieved** — Stage 0 Foundation (wgmesh core functional)
- **Achieved** — Stage 1 Dogfood (internal daily use)
- **Achieved** — Stage 2 Presence (landing page live, install works)
- **Achieved** — Stage 3 Reachable (Open Collective billing live)
- **Open** — Stage 4 Pipeline → Stage 5 Revenue (first paying customer)

---

## Now — committed, in progress

### Cost governance (T1–T5)
**Status:** ADR Accepted 2026-08-30  ·  **Plan:** `../plans/2026-08-30-enforceable-cost-governance-plan.md`
**Track:** Self-heal & resilience

Automaton-extended TreasuryPolicy: typed caps with machine deny codes, SQLite SpendTracker
hourly/daily windows, goose/runner.py preflight gate, inference daily cap via `STAGE_ROUTING`,
cached last-known-balance fail-safe.

- T1 COST_POLICY config
- T2 SQLite SpendTracker windows
- T3 goose/runner.py preflight gate (machine deny codes)
- T4 inference daily cap via STAGE_ROUTING
- T5 cached last-known-cost fail-safe

Rollback = unset env var. Order: T1 → T5.

### Lang-triad cutover completion
**Status:** ~80% built, cutover not complete  ·  **Doc:** `2026-06-23-lang-triad-roadmap.md`
**Track:** Convergence engine

LangChain is live; LangGraph is built but defaults to `legacy`; Langfuse auto-trace not wired;
2 Goose hardcoded surfaces remain in observation assess + decision proposal.

- Phase 0 — verify live truth (GRAPH_IMPL, Langfuse callback wiring, Goose-surface inventory)
- Phase 1 — route observation + decision through `build_executor()`
- Phase 2 — cut over LangGraph on the box
- Phase 3 — wire Langfuse `CallbackHandler` into agents' `callbacks=` config

### #1599 box cutover
**Status:** Open since 2026-08-29  ·  **Track:** Convergence engine

Box never shadow-re-enabled after the accept-gate refactor. Blockers:
- forge-agnostic accept-gate not yet validated
- GTM material still on wgmesh main (`docs/comparison/`, `docs/outreach-communities.md`,
  `docs/outreach-templates.md`, `pkg/referral/`)
- staged shadow-proven re-enable sequence not scripted

---

## Next — scoped, high confidence

### 2nd seed product entering convergence engine
**Status:** STRATEGY milestone 2026-06-14 overdue  ·  **Track:** Convergence engine

wgmesh is the first seed. A second product (or the cloudroof-eu service layer) needs to enter
the pipeline spec → impl → merge lane to demonstrate the framework is not single-repo-dependent.

Deliverable: spec PR opened against the second seed repo, routed through the convergence engine
with zero manual intervention.

### Revenue surface hardening
**Status:** Stage 3 → Stage 4 transition pending  ·  **Track:** Customer Factory / Revenue

- Open Collective tiers reviewed for conversion clarity
- First paying-customer onboarding path documented
- cloudroof-eu signup → first invoice flow automated

---

## Later — planned, lower confidence

### Revenue milestones
| Target | Date | Gate |
|---|---|---|
| First paying customer (Stage 4) | Open | Pipeline first customer |
| 4 customers, $10K ARR run-rate | 2026-08-31 | — |
| 42 customers, $10K ARR | 2027-05-03 | — |
| 420 customers, $100K ARR (MSC) | 2028-05-03 | — |

### Lang-triad Phase 4+: LangGraph production hardening
Once cutover is live: add parity tests, document executor swap procedure, instrument
self-heal triggers against the new graph runtime.

### MSC-scale observability
Langfuse full wiring → cost-per-stage scoring → automated anomaly alerting before
SpendTracker caps are hit. Grounded in cost-governance T5 completion.

---

## Open debt

| Item | Filed | Tracker |
|---|---|---|
| #1599 box cutover | 2026-08-29 | memory `wing_ai-pipeline-template/decisions` |
| Cost governance T1–T5 | 2026-08-30 | `../plans/2026-08-30-enforceable-cost-governance-plan.md` |
| Lang-triad cutover | 2026-06-23 | `2026-06-23-lang-triad-roadmap.md` |
| GTM off wgmesh main | 2026-08-29 | — |

