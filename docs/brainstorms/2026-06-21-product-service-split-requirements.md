# Product / Service Split — Requirements

**Date:** 2026-06-21
**Status:** Ready for planning
**Scope:** Deep — product (establishes the surface model the pipeline routes by)

## Problem

The autonomous pipeline runs a **single seed funnel** pointed at one repo (`atvirokodosprendimai/wgmesh`) via `pulse_seed_product_repo`. Everything the company generates — product code *and* go-to-market work — lands there as wgmesh issues. The result:

- ~90% of the wgmesh aged backlog is **service/GTM work** (outreach, ROI calculator, landing pages, Stripe, referral, analytics), not product code.
- 8 `needs-human` items sit permanently stuck in a **code funnel** — you cannot `merge` "outreach to 50 communities" or "$500 ad experiment."
- Revenue attribution is unreadable: wgmesh and cloudroof are one bucket, so product traction (stars, releases) cannot be told apart from service revenue (subscribers). The loop-history assessments hit this repeatedly (*"seed products remain 0"*).

The split is **already mandated** by `company/CONSTITUTION.md` (wgmesh = AGPL/free product; cloudroof = managed/paid service) but is **structurally absent**: `goal-sprint` single-targets wgmesh, and `pipeline/wgmesh_pipeline/observation.py` routes only `fn:dev` vs `needs-human` with no product/service branching (`fn:dev` even wins ties, line ~198).

## Goal / outcome

Two parallel autonomous funnels — **wgmesh (product)** and **cloudroof (service)** — each with its own repo, roadmap, ideation, triage, and decision stream. Each surface's work terminates where it actually completes (code → merge, social → publish, capital → human), so nothing is misfiled and attribution is legible.

## Primary actors & surfaces

| Surface | What it is | Repo | Funnel terminal |
|---|---|---|---|
| **wgmesh** | AGPL WireGuard mesh **product** | `atvirokodosprendimai/wgmesh` | code → spec→impl→judge→merge |
| **cloudroof** | Managed-hosting **service** @ cloudroof.eu | `atvirokodosprendimai/cloudroof-eu` (exists, empty) | code → merge · social/content → Mixpost draft + human publish · capital/pricing/cold-outreach → `needs-human` / Quackback |

Decision-makers: the **founder** (product + GTM judgment, capital, pricing, public-publish tap) via Quackback; the **autonomous pipeline** (ideation, build, draft) up to each irreversible boundary.

## Decisions (resolved this brainstorm)

1. **cloudroof is a fully autonomous funnel** — it ideates *and* builds both code and GTM, end-to-end, parallel to wgmesh. It is not a human-fed code surface.
2. **"Fully autonomous" stops at the established human gate, not before it.** The pipeline runs ideate → build → draft autonomously; the **one-click human publish** (shipped 2026-06-19, `wgmesh-social-drip.yml`) remains the only gate, at the irreversible public/capital boundary. This is the accepted pattern (*"a glance + one click"*), not a new constraint.
3. **GTM terminals are per-channel:** social/content → **Mixpost draft → human publish** (reuse existing rail); code → **cloudroof-eu merge**; capital ($ spend), pricing, and cold outreach to named people → **`needs-human` / Quackback GTM-decision stream** per CONSTITUTION.
4. **Quackback carries two decision streams** — **product decisions** vs **go-to-market decisions** — with distinct reviewer hat, cadence, and SLA. This reshapes the in-flight `feat/quackback-decision-layer` branch.
5. **The Mixpost publish rail is shared infra, reused as-is.** What splits is *sourcing + ideation + routing*, not the publish mechanism. cloudroof GTM posts source from cloudroof growth context, not wgmesh PRs.

## Requirements

- **R1 — Surface taxonomy.** Introduce an explicit `surface` axis (`product` | `service`) orthogonal to the existing `product` vs `meta` axis in `STRATEGY.md`. Every generated issue is tagged to exactly one surface at creation.
- **R2 — Routing by surface + kind.** `observation.py` (and any create-routing) must route a proposed item to one terminal: product-code → wgmesh; service-code → cloudroof-eu; service-GTM-social → Mixpost-draft lane; service-GTM-capital/pricing/outreach → `needs-human`/Quackback. The current `fn:dev`-beats-`needs-human` tie-break must not strand a GTM task in the code lane.
- **R3 — Dual goal-sprint routing.** `goal-sprint` ideation must emit product ideas into wgmesh and service/GTM ideas into the cloudroof surface, instead of single-targeting one repo.
- **R4 — Two repos, two roadmaps.** wgmesh and cloudroof-eu each carry their own backlog/roadmap/triage. No cross-posting of service work into the product repo.
- **R5 — Quackback stream split.** The decision layer exposes product-decision and GTM-decision streams as distinct categories (reviewer/cadence/SLA per stream), not one undifferentiated queue.
- **R6 — Pulse dual attribution.** `pulse_seed_product_repo` (single-valued today) becomes product-repo *and* service-repo, so the pulse reads product traction and service revenue separately — closing the attribution gap.
- **R7 — GTM social reuse, re-sourced.** The cloudroof social terminal reuses the `wgmesh-social-drip.yml` pattern (draft via Mixpost API, sanitise gate, Unsend review ping, human publish) with cloudroof growth as the source.
- **R8 — Public-safety preserved.** All autonomous-drafted public content (any surface) passes the existing `company/scripts/sanitise.sh` gate before drafting — no secrets, internal data, PII, or exact revenue.

## Scope boundaries

**In:** the surface taxonomy + routing; dual goal-sprint emit; two repos/roadmaps/triage; Quackback stream split; pulse dual attribution; STRATEGY.md product-vs-service axis; re-sourced cloudroof social terminal.

**Deferred for later:** the cloudroof-eu **code funnel's internal mechanics** (it mirrors wgmesh's spec→impl→judge→merge — a planning/exec concern, not a shape decision); new social channels (X/LinkedIn/Reddit, already deferred in the social-drip brainstorm); auto-publish-after-timeout.

**Outside this product's identity:** rebuilding or replacing the Mixpost rail; unattended auto-publish to public accounts (explicitly rejected); monetizing the wgmesh product itself (revenue lives only in the cloudroof managed layer per CONSTITUTION — the split must not create a paywalled product surface).

## Success criteria

- A generated GTM task never lands as a wgmesh code PR/issue; product-code and service-work are separable by surface tag at creation.
- The pulse reports wgmesh traction and cloudroof revenue as distinct lines; the "seed products remain 0" attribution ambiguity is gone.
- Each funnel reaches a real terminal: code merges, social drafts await one publish tap, capital/pricing wait on a founder decision — zero items stuck in the wrong terminal.
- The misfiled aged backlog is dispositioned under the new routing (re-homed or regenerated), not left orphaned.

## Dependencies / assumptions

- `cloudroof-eu` repo exists but is empty — assumed to be the service code home; needs scaffolding (planning).
- Mixpost Pro rail (infrawei instance, @wgmesh on Bluesky+Mastodon, draft→human-publish) is live and reusable — verified via `wgmesh-social-drip.yml` and `docs/brainstorms/2026-06-19-wgmesh-social-drip-requirements.md`.
- `company/CONSTITUTION.md` product/service split is authoritative and already requires this; this brainstorm operationalizes it.
- **Assumption:** the in-flight `feat/quackback-decision-layer` can absorb a stream-category dimension without a redesign — to validate against that branch in planning.
- **Assumption:** a surface tag at issue-creation is sufficient routing signal; the LLM proposer can classify surface reliably — to validate in planning.

## Outstanding questions (for planning)

- **Q1.** Separate **@cloudroof** social account, or cloudroof growth posts go out under a shared brand account?
- **Q2.** Does cloudroof GTM ideation get its **own goal-sprint cadence**, or one sprint emitting surface-routed ideas?
- **Q3.** The misfiled aged backlog (11 wgmesh PRs + GTM issues) — **re-home to cloudroof-eu** vs **close-and-regenerate** under the new routing?
- **Q4.** Does the cloudroof code funnel need its own judge/merge gate instance, or reuse wgmesh's `impl-judge` config pointed at the new repo?
- **Q5.** Where does the surface tag live — a label (`surface:product`/`surface:service`), a separate field, or repo-of-record alone?

## Handoff

Next: `/ce-plan` on this doc to sequence the change — surface taxonomy + `observation.py` routing first (unblocks everything), then goal-sprint dual-emit, Quackback stream split (coordinate with `feat/quackback-decision-layer`), pulse dual attribution, and cloudroof-eu scaffolding. The aged-backlog disposition (Q3) is a fast-follow once routing exists.
