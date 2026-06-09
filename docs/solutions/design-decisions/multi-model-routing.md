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

## Deferred

- **Escalate-on-fail (Phase 2).** When the gate escalates for a *quality* reason (tests
  failed / blocking finding) rather than a structural high-risk one, re-run the stage once
  on a stronger model before labeling `needs-human`. Needs a retry budget, loop-guard, and
  cost ceiling — its own plan. The static map here is the precondition.
- **Native non-Anthropic providers.** Only `native` Anthropic and `openrouter` are wired;
  any other native provider raises with "route it via OpenRouter". Add native support per
  provider when a subscription's own API proves worth the credential.
- **Model-ranking / eval harness.** Choosing the map is a human decision fed by the
  Langfuse cost+score data, not an automated ranker.

## References

- Plan: `docs/plans/2026-06-09-001-feat-multi-model-routing-plan.md`
- Code: `pipeline/wgmesh_pipeline/models.py`, `goose/runner.py`, `config.py`
- Builds on: goose Langfuse cost capture (commit `0c11c3b`, price/perf #1)
