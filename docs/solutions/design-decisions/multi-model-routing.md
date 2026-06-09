---
title: "Multi-model routing: static per-stage map with hybrid billing"
category: design-decisions
date: 2026-06-09
tags: [pipeline, langgraph, goose, price-performance, langfuse, models, routing]
---

## Problem

Every LLM stage in the pipeline ran one hardcoded model (`GLM-4.7` via z.ai's
Anthropic-compatible endpoint), built once from a single `Config` and shared by every
node. Two stages actually call the LLM — spec authoring (cheap, structured) and
implementation (capability-critical). Running both on the same model either overpays on
spec or underdelivers on implement, and there was no way to use the other models we can
reach (z.ai/MiniMax subscriptions, DeepSeek/OpenAI/Anthropic metered API).

## Decision

A **model registry** plus a **static stage→model routing map** (`models.py`):

- `ModelProfile{key, provider, model, billing, credential_env, host?}` is the unit of
  routing. `MODEL_REGISTRY` (env JSON) maps logical keys to profiles; `STAGE_ROUTING`
  (env JSON) binds stages to keys. Each LLM node passes its `stage` into `run_recipe`,
  which resolves the profile and builds the Goose env from it.
- **Hybrid billing.** `billing="native"` keeps subscription models on their own endpoint
  (flat-rate only works there); `billing="openrouter"` routes metered models through one
  `OPENROUTER_API_KEY` gateway — minimal new-credential surface.
- **Zero-config default (R7).** Both env vars unset → a single synthesized `default`
  profile from the existing `goose_*` fields. Existing deploys behave identically.

## Why these choices

- **Profile-per-call, not runner-per-stage.** One `GooseRunner`; the model is resolved at
  env-build time. Keeps the timeout/guard/Langfuse logic single-sourced.
- **Killed the global `ANTHROPIC_API_KEY` hijack.** The old code pinned
  `ANTHROPIC_API_KEY`/`ANTHROPIC_HOST` globally, so a second Anthropic-family model
  couldn't coexist with z.ai. Now each profile writes its own provider/host/credential
  per call — z.ai-as-Anthropic and real Anthropic live side by side.
- **Fail-closed.** An unroutable stage, an unknown registry key, or a missing credential
  raises — it never silently falls back to the wrong model (mailservice no-silent-fallback
  lesson). The one allowed implicit default is the zero-config fallback.
- **Credential allowlist intact.** New provider keys are stripped from Goose's general env
  by the fail-closed allowlist and re-added only when a routed profile names them.

## Attribution

Per-model cost/quality must be sliceable to make the routing decisions data-driven. Two
mechanisms:

- **Authoritative (our code):** `scoring.py` tags each run with `spec_model_key` /
  `implement_model_key`, so the Langfuse Scores dashboard slices outcome by model. This
  lands regardless of Goose internals.
- **Best-effort (Goose telemetry):** `build_goose_env` sets `OTEL_RESOURCE_ATTRIBUTES`
  with `wgmesh.stage` + `wgmesh.model_key`. Whether the installed Goose version forwards
  resource attributes onto its OTLP spans is an unverified execution-time detail — do not
  rely on it for attribution; the scoring path is the source of truth.

## Escalate-on-fail ladder (Phase 2 — shipped, price/perf #3)

`STAGE_ROUTING` values may be a **list** of registry keys (cheap→capable→premium). When a
gate rejection is **quality-only** (tests failed / blocking review finding, `risk_tier` low,
`sanitise` ok), the graph re-runs implement→review→gate on the next model up the ladder,
bounded by `min(ladder_length-1, MAX_ESCALATION_ATTEMPTS)` (default 2). The gate is evaluated
side-effect-free (`apply_side_effects=False`) on intermediate passes; the merge/`needs-human`
side-effect applies once, terminally.

**Autonomy lives inside the safety gates.** A `sanitise` failure (security) or any structural
high-risk reason (`risk_tier` high) goes **straight** to `needs-human` — never climbed. A
retry updates the existing impl PR (no per-tier duplicate). Escalation is attributed in
Langfuse (`escalation_tier`, `escalated_recovered`) so escalation rate and tier-resolution
chart out. A scalar route → single-shot, exactly as before (fail-safe-off).

**Cost ceiling is bounded attempts, not a live $-cap.** Goose runs as a subprocess and reports
token cost to Langfuse *asynchronously* — the runner gets no synchronous usage number — so a
true per-issue dollar cap isn't implementable without new plumbing. The enforced bound is
attempt-count + quality-only triggering. Plan:
`docs/plans/2026-06-09-002-feat-escalate-on-fail-ladder-plan.md`.

## Deferred

- **Native non-Anthropic providers.** Only `native` Anthropic and `openrouter` are wired;
  any other native provider raises with "route it via OpenRouter". Add native support per
  provider when a subscription's own API proves worth the credential.
- **Model-ranking / eval harness.** Choosing the map is a human decision fed by the
  Langfuse cost+score data, not an automated ranker.

## References

- Plan: `docs/plans/2026-06-09-001-feat-multi-model-routing-plan.md`
- Code: `pipeline/wgmesh_pipeline/models.py`, `goose/runner.py`, `config.py`
- Builds on: goose Langfuse cost capture (commit `0c11c3b`, price/perf #1)
