# Requirements: Gate + route cloudroof (service) issues out of the wgmesh builder

**Date:** 2026-06-21
**Scope tier:** Deep — feature (extends the #1931 product/service split)
**Origin:** `/ce-debug` session — issue #783 ("onboarding checklist widget on cloudroof dashboard") was filed in wgmesh, the spec agent reinterpreted it as a wgmesh terminal/daemon feature, the impl built off-spec `pkg/daemon` code, and the judge rejected it — a wasted spec+impl+judge cycle.

---

## Problem Frame

PR #1931 shipped the product/service split machinery — `surface:product`/`surface:service` labels, routing constants (`SURFACE_REPO = {"product": wgmesh, "service": cloudroof-eu}`), and `_route_lane_and_repo()` (`pipeline/wgmesh_pipeline/observation.py:48–256`). But that routing fires **only inside the observation loop** (LLM-ideated issues). Three entry points bypass it, so service issues still reach the wgmesh impl builder:

1. **Manually-filed issues** — `observation.py` only processes LLM assessments; an issue filed directly on GitHub (like #783: `fn:dev`, `copilot-triaging`, **no surface label**) never hits `_route_lane_and_repo`.
2. **No builder-entry gate** — `triage.py` classifies `wont-do | needs-info | feature | fix` only; it does not check surface. A service issue in wgmesh proceeds to spec→impl unfiltered.
3. **No fail-safe on unknown surface at the builder** — an unclassified issue with `fn:dev` advances and gets built in wgmesh.

The result is wasted autonomous cycles and off-spec code. The judge catches the output, but the cost (spec + impl + judge) is already spent.

## Goal

A surface-aware **gate + router** at the builder entry that makes it structurally impossible for a service-scoped (or unclassified) issue to be built in the wgmesh pipeline, and routes detected service issues toward cloudroof-eu through a cofounder decision gate.

## Requirements

- **R1 — Classify surface on every issue entering the builder.** Every issue that reaches the build pipeline carries a `surface:product` or `surface:service` classification, including manually-filed issues that bypass the observation loop today. Reuse the surface-classification prompt already used by the LLM gather (`observation_gather.py:290–301`).
- **R2 — Load-bearing builder gate (the fail-safe).** A `surface:service` issue NEVER advances to spec→impl in the wgmesh pipeline. An **unknown/unclassified** surface BLOCKS spec→impl until surface is assigned (classify inline, else hold) — it does not default to product. This is the gate that directly prevents the #783 path.
- **R3 — Route detected service issues to cloudroof-eu + the cofounder decision gate.** A detected service issue is relocated toward `cloudroof-eu` (reuse `_route_lane_and_repo`) AND surfaced in Quackback's **gtm-decision stream** so a cofounder decides whether it is worth building before it consumes build effort. High-confidence service → route; low/ambiguous confidence → human queue.
- **R4 — Fail-safe by default.** Any ambiguity (unknown surface, low classification confidence) resolves to the human queue (`needs-human` / Quackback), never to a silent wgmesh build.
- **R5 — Reuse, don't duplicate.** Build on the existing #1931 surface labels, `SURFACE_REPO`, and `_route_lane_and_repo`; the deliverable is wiring them at the **triage/builder entry** and covering the **manual-issue** path, not new routing primitives.

## Key Decisions

- **KD1 — The gate lives at the builder entry (triage/poller), not only at observation routing.** Manual issues bypass the observation loop, so a builder-entry gate is the only place that catches all entry paths. This is the root-cause fix for #783.
- **KD2 — Unknown surface blocks; it does not default to product.** #783 had no surface label and was built anyway. Defaulting unknown→product re-opens that exact leak.
- **KD3 — Disposition flows through Quackback's gtm-decision stream, not pure auto-build.** Operator: *"either way we need this quack something to make sure co-founders want to spend time on those things."* Service/GTM work needs human judgment on whether it is worth doing — a cofounder accept-gate (the existing Quackback front gate / two-stream contract) sits in front of cloudroof build effort.

## Scope Boundaries

### In scope
- Surface classification at triage for all builder-bound issues (incl. manual).
- Builder-entry gate: refuse `surface:service`; block unknown-surface until classified.
- Route detected service issues to cloudroof-eu + surface them in the Quackback gtm-decision stream.

### Deferred to follow-up
- The cloudroof-eu **autonomous builder** (a pipeline pointed at cloudroof-eu). cloudroof-eu exists but is nascent (tiny Cloudflare site, 0 issues).
- goal-sprint **dual-surface emission** (#1931 U4 — still hardcoded to `pulse_seed_product_repo` = wgmesh).
- cloudroof **GTM/content terminal** (non-code service work).
- **Backfill** — reclassifying the existing aged wgmesh backlog of service-scoped issues (e.g. #786, #789) — candidate one-shot sweep, separate from the standing gate.

### Outside this product's identity
- Monetizing or gating wgmesh (product) itself — revenue lives only at the cloudroof (service) layer per CONSTITUTION.md. This effort enforces that boundary; it does not move it.

## Success Criteria

- A `surface:service` or unclassified issue filed directly in wgmesh does **not** reach spec→impl (would have stopped #783).
- Detected service issues appear in cloudroof-eu and in the Quackback gtm-decision stream for cofounder triage.
- Zero off-spec "service-feature-built-in-wgmesh" impl PRs after rollout (the #783 class goes to zero).

## Dependencies & Assumptions

- **cloudroof-eu repo exists** (verified — nascent Cloudflare Workers site). Valid routing target; its builder is out of scope.
- **Quackback gtm-decision stream** (`docs/quackback-decision-streams.md`, #1931 U7) is assumed usable as the cofounder gate. **Unverified whether it is live/wired** — if not, service issues park via `needs-human` until it is (see Open Questions).
- **Surface classifier reuse** — the triage-time classifier reuses the observation gather's surface prompt; assumes it classifies a bare manual issue (title + body) as reliably as an ideated one.

## Open Questions

- Is the Quackback gtm-decision stream actually live and wired, or still spec? Determines whether R3 routes to Quackback now or falls back to `needs-human` until it lands.
- Backfill: reclassify the existing aged wgmesh backlog of service issues in this effort, or as a separate follow-up sweep?
- Cross-repo relocation mechanism (GitHub issue transfer vs recreate-with-pointer) — defer to ce-plan.
