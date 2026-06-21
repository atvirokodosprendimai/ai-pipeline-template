# Quackback Decision Streams — product vs go-to-market

**Status:** Contract (consumed by the `feat/quackback-decision-layer` implementation)
**Date:** 2026-06-21
**Origin:** `docs/plans/2026-06-21-003-feat-product-service-split-plan.md` (U7), `docs/brainstorms/2026-06-21-product-service-split-requirements.md` (R5)

## Purpose

The product/service split (see `CONCEPTS.md` → *Surface*) routes work to two repos and three terminals. The human-decision terminal — Quackback — must mirror that split: a founder reviewing **product** judgment (does this belong in the wgmesh AGPL software?) is wearing a different hat, on a different cadence, than one reviewing **go-to-market** judgment (spend this capital? commit to this price? send this outreach?). One undifferentiated decision queue conflates them and hides which kind of attention is the bottleneck.

This document is the **contract**: it defines the two streams, their routing key, and per-stream fields. It does **not** specify transport, storage, or UI — those land in the `feat/quackback-decision-layer` implementation, which consumes this contract. This file is authoritative on *what the streams are*; that branch is authoritative on *how they are served*.

## The two streams

| | `product-decision` | `gtm-decision` |
|---|---|---|
| **Owns** | What belongs in the wgmesh product, architectural calls, AGPL/values judgments | Capital spend, pricing/packaging, cold outreach to named people, brand/positioning commitments |
| **Surface** | `surface:product` | `surface:service` |
| **Reviewer hat** | Product/engineering judgment | Go-to-market/commercial judgment |
| **Typical items** | "Close or resolve tech-debt #539"; a paywall-shaped spec escalated per CONSTITUTION | "Decide Stripe pricing #778"; "$500 ad experiment #747"; "outreach to 50 stargazers #775" |
| **Default SLA** | 48h (matches the pulse aged-item KPI) | 48h |

Both streams share the 48h decision SLA today — the `pulse_open_age_kpi` aged-item clock already governs both. The streams differ in *who* and *what lens*, not yet in *how fast*; per-stream SLA divergence is a follow-up if attention load demands it.

## Routing key

The stream is selected by the item's **surface label**, which the observation/goal-sprint layers already assign (`pipeline/wgmesh_pipeline/observation.py`):

- `surface:product` + `needs-human` → **`product-decision`** stream.
- `surface:service` + `needs-human` → **`gtm-decision`** stream.
- A `needs-human` item with **no surface label** → fail safe to **`product-decision`** (the lower-blast-radius default — a product reviewer can re-route a mis-tagged GTM item; the reverse risks a commercial commitment made under a product lens). The router SHOULD log the missing-surface case so the upstream classifier can be corrected.

Routing reads the existing label; it introduces no new field. This keeps the contract aligned with the surface axis rather than forking a parallel taxonomy.

## Per-item fields (contract)

Each decision item carried into a stream MUST expose:

- `stream` — `product-decision` | `gtm-decision` (derived from the surface label per above).
- `surface` — `product` | `service` (the source label, retained for audit).
- `title`, `body` — the human-readable decision request (already sanitised upstream per `company/scripts/sanitise.sh`; the decision layer MUST NOT re-expose secrets/PII).
- `created_at` — for the 48h SLA clock (createdAt-based, not updatedAt — matches the aged-item KPI).
- `origin` — the source issue/PR reference, so a decision links back to the work item.

The decision layer MAY add transport-specific fields (assignee, notification target, audit id); those are out of this contract's scope.

## Conformance

The `feat/quackback-decision-layer` implementation conforms when:

1. A `surface:service` + `needs-human` item surfaces in the `gtm-decision` stream and NOT the `product-decision` stream (and vice-versa).
2. A `needs-human` item with no surface label surfaces in `product-decision` and the missing-surface case is logged.
3. Each stream reports its own aged-item count against the 48h SLA, so a GTM-decision pileup cannot hide behind a healthy product-decision queue (mirrors the pulse "both repos" KPI scope).

Conformance tests land with that branch's implementation, against this contract.

## Out of scope (deferred)

- Per-stream SLA divergence (both 48h today).
- Distinct reviewer identities/routing (one founder wears both hats today).
- Transport, storage, notification, and UI — owned by `feat/quackback-decision-layer`.
