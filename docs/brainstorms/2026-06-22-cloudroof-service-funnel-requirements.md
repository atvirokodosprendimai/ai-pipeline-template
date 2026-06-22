# Requirements — Cloudroof service funnel

**Date:** 2026-06-22 · **Status:** ready for ce-plan · **Scope tier:** Deep

## Problem / why now

The product/service split shipped the *gate* (surface-gate #1960 holds `surface:service`
issues out of the wgmesh builder) but never the *service builder*. goal-sprint now emits
mostly `surface:service` (cloudroof GTM) issues → they park as `needs-human` with nowhere to
build → **0 product convergence across ~4 pulses** while the wgmesh product backlog is
exhausted. The autonomous company has built out its product and stalled. The missing
cloudroof-eu funnel is the single highest-leverage constraint on company output.

cloudroof-eu = the monetized service surface (Cloudflare Workers marketing/dashboard site).

## Outcome

A cloudroof site feature flows **autonomously from issue to live deploy** on cloudroof.eu,
on the same box as wgmesh, without a human in the build loop (after an initial calibration
phase). Success = one `surface:service` *code* issue goes issue→spec→impl→PR→merge→deployed
with zero hand edits.

## Decisions (locked in brainstorm)

- **Runtime:** a SECOND `wgmesh_pipeline` instance on the existing Hetzner box, its own
  systemd unit / env / state DB, `TARGET_REPO=cloudroof-eu`. Reuses all machinery (poller,
  graph, executor, forge, merge-lane-heal). No core multi-repo refactor — two processes, not
  one process spanning two repos.
- **Build scope:** the funnel autonomously builds **code site-features only** (landing pages,
  FAQ, email capture, comparison pages — Workers/HTML/JS). **Non-code GTM** (outreach, ad
  spend, Stripe pricing) routes to the cofounder gtm-decision queue, never auto-built.
- **Build gate:** cofounder **accept-gate for the first N builds** (quality/brand
  calibration), then flip to auto-build like wgmesh. Throughput isn't founder-limited once
  trust is established.
- **MVP = the full chain incl. deploy** (slice 1): issue→spec→impl→PR→merge→**wrangler
  deploy** to cloudroof.eu. The first built feature goes live end-to-end.

## Key flows

1. **Intake + classify:** a `surface:service` issue is split code-buildable vs GTM. Code →
   cloudroof funnel queue. GTM → gtm-decision queue (cofounder). Surface-gate's current
   *block+park* for service issues changes to *route to the cloudroof funnel* (for code) /
   *gtm queue* (for GTM).
2. **Accept-gate (first N):** a code issue waits for a cofounder "accepted for build" signal
   before the funnel spends effort; after N proven builds, the gate lifts.
3. **Build:** the cloudroof pipeline instance runs spec→impl→PR against cloudroof-eu; its CI
   is JS/wrangler (not Go); impl-judge applies.
4. **Deploy:** on merge to cloudroof-eu main, `wrangler deploy` publishes to cloudroof.eu.

## Scope boundaries

- **In:** 2nd pipeline instance (unit/env/DB); cloudroof-eu CI (wrangler build/test/typecheck)
  + deploy-on-merge; the accept-gate; surface-gate change (route, not park); code-vs-GTM
  classification at intake.
- **Deferred (later slices):** extending merge-lane-heal + pulse + supervisor to cloudroof;
  backfilling the parked service backlog; flipping the gate off after N.
- **Outside this funnel's identity:** executing non-code GTM (humans do that); the wgmesh
  product pipeline (untouched); the Quackback forge cutover (independent track).

## Dependencies / assumptions / constraints

- **Two pipeline processes on one cpx22 box** → ~2× LLM/CI/git load. Resource headroom +
  per-process isolation (distinct DB path, env file, systemd unit, bot-PAT scope for
  cloudroof-eu) is a real constraint — verify the box can carry it, or size up.
- **Deploy needs a Cloudflare API token** (Workers deploy) as a box/CI secret — not present
  in this repo today (assumption: cloudroof-eu deploys via wrangler; confirm the CF account).
- **Accept-gate mechanism:** Quackback gtm-stream is a label-keyed contract but **not live**
  (deferred to `feat/quackback-decision-layer`). Interim gate = a GitHub label a cofounder
  adds (e.g. `accepted-for-build`), Quackback-stream-compatible. (assumption)
- cloudroof-eu is nascent (Workers site, 0 issues, no CI in-repo). The funnel must create its
  own CI there. (verified via grounding scout)
- The bot PAT must have read+write on cloudroof-eu (the merge-lane-heal cutover proved the box
  token reads both wgmesh+meta; cloudroof-eu access is unverified — confirm).

## Outstanding questions (→ ce-plan)

- Gate mechanism: GitHub label now vs wait for Quackback? (lean: label now.)
- The "first N" threshold before auto-build flips.
- Does the cloudroof CI reuse a shared workflow or get its own? (cloudroof-eu repo, JS stack.)
- Box capacity for a 2nd process, or size up the VM?
- Does goal-sprint emit cloudroof code-feature issues directly into cloudroof-eu, or stay in
  wgmesh + route at intake?

## Grounding

`/tmp/compound-engineering/ce-brainstorm/cloudroof-funnel/grounding.md`. Prior art:
`docs/brainstorms/2026-06-21-cloudroof-issue-routing-gate-requirements.md`,
`docs/plans/2026-06-21-003-feat-product-service-split-plan.md`,
`docs/plans/2026-06-21-008-feat-surface-gate-builder-entry-plan.md`. Memory:
project_product_service_split, project_quackback_decision_layer, project_merge_lane_heal_to_box.
