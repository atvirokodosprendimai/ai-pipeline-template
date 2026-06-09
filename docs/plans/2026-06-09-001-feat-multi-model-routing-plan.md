---
title: "feat: Multi-model routing for the pipeline (price/perf #2)"
status: active
date: 2026-06-09
type: feat
origin: none (solo ce-plan from price/perf series)
---

# feat: Multi-model routing for the pipeline (price/perf #2)

## Summary

Today every LLM-invoking pipeline stage runs one hardcoded model (`GLM-4.7` via
z.ai's Anthropic-compatible endpoint). This plan turns that single model into a
**model registry + static stage→model routing map**: register every model we can
reach (z.ai/GLM and MiniMax subscriptions, DeepSeek and OpenAI/Anthropic metered
API), assign a model to each LLM stage by cost/capability, and route each Goose
invocation to its assigned model. Plumbing is **hybrid** — flat-rate subscriptions
keep their native endpoints, metered models go through one OpenRouter gateway.

This is the routing half of price/performance. The measurement half (Goose →
Langfuse per-model cost capture) already landed in commit `0c11c3b`. Routing
makes the cost data actionable: cheap models on cheap stages, capable models where
quality matters, every choice attributed in Langfuse by stage **and** model.

Escalate-on-fail (run cheap, retry on a stronger model when the gate fails) is
**explicitly Phase 2** — deferred to follow-up. This plan ships the static map only.

---

## Problem Frame

`GooseRunner` is constructed once from a single `Config` and every node that calls
`run_recipe` inherits the same `GOOSE_MODEL` / `GOOSE_PROVIDER`. Two stages actually
hit the LLM today:

- **spec** (`spec_node`, recipe `wgmesh-triage-spec.yaml`) — issue → spec authoring
- **implement** (`implement_node`, recipe `wgmesh-implementation.yaml`) — spec → diff

`triage`, `review`, and `gate` are deterministic (heuristics, `sanitise.sh`, risk
rules) — no LLM, not in routing scope yet. Spec authoring is cheap, structured work;
implementation is the capability-critical stage. Running both on the same model
either overpays on spec or underdelivers on implement. There is no mechanism to
assign different models per stage, and the z.ai path currently **hijacks**
`ANTHROPIC_API_KEY` + `ANTHROPIC_HOST` globally — so a second Anthropic-family model
(real Anthropic) cannot coexist with z.ai under the current env build.

**In scope:** model registry, static stage→model map, per-call model resolution in
the Goose env builder, threading stage identity from the two LLM nodes, credential
allowlist + provision wiring, per-stage/per-model cost attribution.

**Out of scope:** changing the LangGraph topology or funnel logic; escalate-on-fail
retry (Phase 2); any model-ranking/eval harness; routing the deterministic nodes.

---

## Requirements

- **R1** Each LLM-invoking stage resolves its model from a config-driven routing map,
  not a single global.
- **R2** Multiple models from different providers coexist — including two
  Anthropic-family models (z.ai-as-Anthropic and real Anthropic) without env collision.
- **R3** Hybrid billing: subscription models (z.ai, MiniMax) use their native
  endpoints; metered models (DeepSeek, OpenAI, Anthropic) route via OpenRouter.
- **R4** Fail-closed: an unknown/misconfigured model key raises, never silently falls
  back to the global default (mailservice lesson: misconfig must fail, not drift).
- **R5** Every Goose generation is attributed in Langfuse by **stage** and **model
  key**, so price/perf dashboards slice both ways.
- **R6** Credentials for new providers are added to the fail-closed allowlist
  explicitly and never leak to the LLM agent's general env.
- **R7** Default behavior with no routing config matches today exactly (single global
  model) — zero-config backward compatibility.

---

## High-Level Technical Design

Model selection moves from "one global env" to "resolve a profile per call":

```
                    ┌──────────────── Config ────────────────┐
                    │  model_registry: {key → ModelProfile}   │
                    │  stage_routing:  {stage → key}          │
                    └──────────────────┬──────────────────────┘
                                       │
  spec_node ──run_recipe(stage="spec")─┤
                                       ├─► GooseRunner.resolve(stage)
  implement_node ─(stage="implement")──┘        │
                                                ▼
                                   ModelProfile{provider, model,
                                     host, credential_env, billing}
                                                │
                                   build_goose_env(profile)
                                                │
                            ┌───────────────────┴───────────────────┐
                        native (subscription)              openrouter (metered)
                   GOOSE_PROVIDER=anthropic|...       GOOSE_PROVIDER=openrouter
                   ANTHROPIC_HOST=<z.ai|...>          OPENROUTER_API_KEY=<key>
                   <CRED>=<key>                       GOOSE_MODEL=<or-slug>
```

A `ModelProfile` is the unit of routing. The registry maps a logical key
(`"spec-cheap"`, `"impl-capable"`) to a profile. The stage map binds stages to keys.
`build_goose_env` becomes a pure function of `(safe base env, profile, langfuse
creds)` instead of reading model fields off `Config` directly.

`ModelProfile` (directional shape, not final signature):

```python
@dataclass(frozen=True)
class ModelProfile:
    key: str                 # logical name, e.g. "impl-capable"
    provider: str            # goose provider id: anthropic | openrouter | ...
    model: str               # goose model id / openrouter slug
    billing: str             # "native" | "openrouter"
    host: str | None         # endpoint for native non-default (z.ai, minimax)
    credential_env: str      # env var name holding this model's key
```

---

## Key Technical Decisions

- **KTD1 — Profile-per-call, not runner-per-stage.** Keep one `GooseRunner`; pass a
  stage/model key into `run_recipe` and resolve a `ModelProfile` at env-build time.
  Avoids N runner instances and keeps the Langfuse/timeout/guard logic single-sourced.
- **KTD2 — `build_goose_env` parametrized by profile.** Each profile sets its OWN
  provider + host + credential at env-build time. This is what lets z.ai-as-Anthropic
  and real-Anthropic coexist (R2): the global `ANTHROPIC_API_KEY` hijack is removed;
  the credential is written per-call from `profile.credential_env`.
- **KTD3 — OpenRouter as the metered gateway.** `OPENROUTER_API_KEY` is already in the
  runner's `_KNOWN_SECRET_NAMES`. One key reaches DeepSeek/OpenAI/Anthropic via slugs
  — minimal new-credential surface for the metered tier (R3). Subscriptions stay
  native because flat-rate billing only applies on their own endpoints.
- **KTD4 — Zero-config fallback.** When no registry/routing is configured, synthesize a
  single implicit profile from today's `goose_provider`/`goose_model`/`anthropic_host`
  fields and route all stages to it. Existing deploys behave identically (R7).
- **KTD5 — Fail-closed resolution.** A stage mapped to a missing registry key, or a
  profile missing its credential, raises at resolution — no silent global fallback (R4).
- **KTD6 — Registry/map via env JSON.** Provide registry + stage map as JSON env vars
  (`MODEL_REGISTRY`, `STAGE_ROUTING`) parsed in `load_config`, mirroring the existing
  env-driven config style. Keeps secrets out of the JSON (only key *names* referenced;
  values come from their own env vars).

---

## Output Structure

No new top-level directories. Touches existing `pipeline/wgmesh_pipeline/` modules and
adds focused test files alongside the current `pipeline/tests/` suite.

---

## Implementation Units

### U1. Model registry + stage routing in config

**Goal:** Define `ModelProfile`, parse a model registry and stage→key map from env,
expose them on `Config` with a zero-config fallback profile.

**Requirements:** R1, R3, R4, R7, KTD4, KTD6

**Dependencies:** none

**Files:**
- `pipeline/wgmesh_pipeline/config.py` (modify — add `ModelProfile`, registry/map fields, parsing)
- `pipeline/wgmesh_pipeline/models.py` (create — `ModelProfile`, registry resolution, fallback synthesis)
- `pipeline/tests/test_models.py` (create)
- `pipeline/tests/test_config.py` (modify — registry/map parsing cases)

**Approach:** New `models.py` owns `ModelProfile`, `parse_registry(json)`,
`parse_stage_routing(json)`, and `resolve_profile(registry, routing, stage)` with
fail-closed errors. `load_config` reads `MODEL_REGISTRY` / `STAGE_ROUTING` (optional
JSON). When both absent, build a one-entry registry `{"default": <profile from
goose_provider/goose_model/anthropic_host/ZAI_API_KEY>}` and route every stage to it.
Billing field is `"native"` for the fallback.

**Patterns to follow:** `_get_nonempty` / `_get_int` env helpers and the explicit
`ValueError` raising style already in `config.py`; `@dataclass(frozen=True)` like `Config`.

**Test scenarios:**
- Happy: valid `MODEL_REGISTRY` JSON with two profiles parses to two `ModelProfile`s.
- Happy: `STAGE_ROUTING` `{"spec":"a","implement":"b"}` resolves each stage to its key.
- Zero-config: both env vars unset → single `default` profile synthesized from existing
  goose fields; `resolve_profile(...,"implement")` returns it.
- Edge: registry present, routing maps a stage to a key not in registry → raises (R4).
- Edge: profile references `credential_env` whose env var is unset → resolution raises.
- Edge: malformed JSON in `MODEL_REGISTRY` → `ValueError` naming the var.
- `billing` accepts only `native|openrouter`; other value → raises.

### U2. Parametrize Goose env build by ModelProfile

**Goal:** Make `build_goose_env` a function of a `ModelProfile`, removing the global
`ANTHROPIC_API_KEY` hijack so multiple providers (incl. two Anthropic-family) coexist.

**Requirements:** R2, R3, R5, R6, KTD1, KTD2

**Dependencies:** U1

**Files:**
- `pipeline/wgmesh_pipeline/goose/runner.py` (modify — `build_goose_env(profile, base_env, langfuse)`, profile→provider/host/cred mapping)
- `pipeline/tests/test_goose_env.py` (modify — per-profile env cases)

**Approach:** `build_goose_env` takes a `ModelProfile`. For `billing="native"`: set
`GOOSE_PROVIDER=profile.provider`, `GOOSE_MODEL=profile.model`, write the credential to
the provider's expected var (Anthropic family → `ANTHROPIC_API_KEY` + `ANTHROPIC_HOST`
from `profile.host`). For `billing="openrouter"`: `GOOSE_PROVIDER=openrouter`,
`GOOSE_MODEL=profile.model` (slug), `OPENROUTER_API_KEY` from the profile credential.
Langfuse cost-capture block (the landed `0c11c3b` logic) stays, plus add the model key
as metadata so generations are attributable (R5 — see U5). Credential value is read from
`os.environ[profile.credential_env]` via the safe base env, never globally pinned.

**Patterns to follow:** existing allowlist `build_goose_env` structure; keep the
fail-closed `_is_safe_var` filter and re-add only profile + langfuse vars.

**Test scenarios:**
- Native Anthropic profile (z.ai) → env has `GOOSE_PROVIDER=anthropic`, `ANTHROPIC_HOST`
  = z.ai host, `ANTHROPIC_API_KEY` = that profile's key.
- Second native Anthropic profile (real Anthropic, different host/key) built in the same
  process → distinct env, no collision with z.ai (R2 regression guard).
- OpenRouter profile → `GOOSE_PROVIDER=openrouter`, `OPENROUTER_API_KEY` set,
  `GOOSE_MODEL` = slug, no `ANTHROPIC_*`.
- Box PAT / unrelated secret in base env → still stripped (allowlist intact).
- Langfuse creds present → `LANGFUSE_URL/PUBLIC_KEY/SECRET_KEY` still exported.
- Profile credential env var missing → raises (matches U1 fail-closed).
- Covers AE: a single run building envs for two stages yields two different `GOOSE_MODEL`s.

### U3. Thread stage identity through the runner and LLM nodes

**Goal:** `run_recipe` accepts a stage/model key, resolves the profile, and builds env
from it; `spec_node` and `implement_node` declare their stage.

**Requirements:** R1, KTD1, KTD5

**Dependencies:** U1, U2

**Files:**
- `pipeline/wgmesh_pipeline/goose/runner.py` (modify — `run_recipe(..., stage: str)`, resolve via config registry/map)
- `pipeline/wgmesh_pipeline/graph/nodes/spec.py` (modify — pass `stage="spec"`)
- `pipeline/wgmesh_pipeline/graph/nodes/implement.py` (modify — pass `stage="implement"`)
- `pipeline/tests/test_runner_routing.py` (create)

**Approach:** `GooseRunner` resolves `ModelProfile` from `config` registry/map using the
`stage` arg, then calls `build_goose_env(profile, ...)`. Default `stage` resolution falls
through to the zero-config `default` profile (U1) so callers without a mapped stage still
work. Nodes pass a literal stage string; no other node logic changes.

**Patterns to follow:** existing `run_recipe` signature and `GooseResult` flow; keep
subprocess/timeout/guard code untouched — only the `env=` source changes.

**Test scenarios:**
- `run_recipe(stage="spec")` with a routed registry uses the spec profile's model
  (assert via injected `SubprocessRunner` capturing `env`).
- `run_recipe(stage="implement")` uses the implement profile's model.
- Stage not in routing map but `default` exists → uses default (zero-config path).
- Stage not in map and no default → raises (R4/KTD5).
- `spec_node` end-to-end with a fake runner records `stage="spec"` was requested.
- `implement_node` likewise for `stage="implement"`.

### U4. Credentials allowlist + provision wiring

**Goal:** Admit the new provider credentials through the fail-closed allowlist and supply
them to the box, without leaking to the agent's general env.

**Requirements:** R3, R6

**Dependencies:** U2

**Files:**
- `pipeline/wgmesh_pipeline/goose/runner.py` (modify — add new cred names to `_KNOWN_SECRET_NAMES`)
- `.github/workflows/provision-pipeline-box.yml` (modify — pass new secrets to box env)
- `pipeline/tests/test_goose_env.py` (modify — leak-guard for new creds)

**Approach:** Add `MINIMAX_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY` to
`_KNOWN_SECRET_NAMES` (so the allowlist strips them by default; `OPENROUTER_API_KEY` and
`ANTHROPIC`-family markers already covered). Each is re-added to the subprocess env ONLY
when a routed profile names it as its `credential_env` (U2). Provision workflow forwards
the secrets to the box's environment/secret store the same way `ZAI_API_KEY` is handled
today. No secret values appear in registry JSON — only var names.

**Patterns to follow:** the existing `_KNOWN_SECRET_NAMES` set and the secret-forwarding
block for `ZAI_API_KEY` in the provision workflow.

**Test scenarios:**
- Each new cred in base env is stripped from a profile env that does NOT reference it.
- A profile that references `DEEPSEEK_API_KEY` (via OpenRouter slug or native) gets only
  the one credential it needs, not the others.
- `Test expectation: workflow YAML` change verified by U1–U3 unit coverage + a lint that
  the new secrets are referenced; no behavioral unit test for the YAML itself.

### U5. Per-stage / per-model cost attribution

**Goal:** Tag Goose's Langfuse generations with stage + model key so price/perf
dashboards slice by both.

**Requirements:** R5

**Dependencies:** U2, U3

**Files:**
- `pipeline/wgmesh_pipeline/goose/runner.py` (modify — set Langfuse metadata/tags env for stage+model_key)
- `pipeline/wgmesh_pipeline/scoring.py` (modify — include `model_key` in score tags where a stage's model is known)
- `pipeline/tests/test_goose_env.py` (modify — assert attribution env present)
- `pipeline/tests/test_scoring.py` (modify — `model_key` in tags)

**Approach:** When building env for a stage, export the stage name and resolved
`model_key` as Langfuse metadata (via Goose's supported metadata/tags env, or a
`LANGFUSE_*` tag var Goose honors — verify identifier at impl, see Deferred). Extend
`LangfuseScorer.record` tags to carry `model_key` so the online score and the cost trace
join on stage+model.

**Patterns to follow:** the landed cost-capture block in `build_goose_env`
(`0c11c3b`); existing `tags` dict shape in `scoring.py`.

**Test scenarios:**
- Env for `stage="implement"` includes stage + model_key attribution metadata.
- Scorer `record(...)` tags include `model_key` for a routed run.
- Zero-config run still records a stable `model_key` (`"default"`), not empty.

### U6. Defaults, docs, and operating-prompt note

**Goal:** Document the routing map, record the default stage→model assignments, and note
the price/perf boundary (static now, escalate-on-fail later) where operators read it.

**Requirements:** R7

**Dependencies:** U1–U5

**Files:**
- `AGENTS.md` (modify — model routing section: how to configure registry/map)
- `company/system-prompt.md` (modify — one line on frugality: cheap stages get cheap models)
- `docs/solutions/` (create — short learning doc on the routing design + hybrid billing)
- `memory/MEMORY.md` (modify — index entry if a memory file is added)

**Approach:** Document `MODEL_REGISTRY` / `STAGE_ROUTING` JSON shape, the recommended
default map (spec → cheapest subscription model; implement → most capable available
within budget), and the hybrid-billing rule (subscriptions native, metered via
OpenRouter). State plainly that escalate-on-fail is Phase 2.

**Patterns to follow:** existing AGENTS.md section style; `docs/solutions/` learning-doc
frontmatter convention.

**Test scenarios:** `Test expectation: none — docs only.`

---

## Scope Boundaries

### Deferred to Follow-Up Work

- **Escalate-on-fail (Phase 2).** When `gate` decides `escalate` for a *quality* reason
  (`tests failed` / `blocking review finding`) rather than a structural high-risk reason,
  re-run `implement` once on a stronger model before labeling `needs-human`. This is the
  dynamic quality floor; it needs a retry budget, loop-guard, and cost ceiling — its own
  plan. The static map here is the precondition.
- **LLM review/judge stage routing.** If a future LLM-backed review node lands, add it to
  the stage map; out of scope now (review is deterministic today).

### Outside this product's identity

- **Model-ranking / eval harness.** Automatically scoring models against each other to
  pick the map is a separate capability, not part of routing. The Langfuse cost+score
  data feeds a human decision for now.

---

## Risks & Dependencies

- **Goose provider identifiers are unverified at plan time.** The exact `GOOSE_PROVIDER`
  ids and credential env names for `openrouter` / `deepseek` / `minimax`, and whether
  Goose honors per-run Langfuse metadata env, must be confirmed against the installed
  Goose version during U2/U5. Treated as an execution-time unknown (below), not a
  planning blocker. If a provider isn't natively supported, route it via OpenRouter.
- **Subscription API access.** Hybrid native billing assumes the z.ai and MiniMax
  *subscriptions* expose API endpoints usable by Goose (z.ai already proven via the
  Anthropic adapter). If MiniMax subscription gives no API, it routes via OpenRouter
  (metered) instead — a config change, no code change.
- **Credential blast radius.** More provider keys on the box = more to rotate. Mitigated
  by the fail-closed allowlist (U4): each key reaches the agent only when a profile names
  it.

### Execution-time unknowns (resolve during implementation, not now)

- Exact Goose provider ids + per-provider credential env var names.
- Whether Goose emits per-run Langfuse metadata via env or requires a config-file knob.
- The concrete default model choices for the shipped map (a budget/quality call the
  operator makes with the cost data).

---

## Sources & Research

Grounded in local code read (no external research run — the design is an internal
refactor of known modules):

- `pipeline/wgmesh_pipeline/goose/runner.py` — `build_goose_env` allowlist + landed
  Langfuse cost capture (`0c11c3b`); `_KNOWN_SECRET_NAMES` already lists `OPENROUTER_API_KEY`.
- `pipeline/wgmesh_pipeline/config.py` — single `goose_provider`/`goose_model` fields,
  `DEFAULT_ANTHROPIC_HOST = https://api.z.ai/api/anthropic`.
- `pipeline/wgmesh_pipeline/graph/nodes/spec.py`, `implement.py` — the only two
  `run_recipe` callers (LLM stages); `triage.py`/`review.py`/`gate.py` deterministic.
- `pipeline/wgmesh_pipeline/graph/build.py` — graph topology (unchanged by this plan).
- Memory: hybrid plumbing and fail-closed allowlist reuse the
  `feedback_agent_env_allowlist_not_denylist` and `feedback_pin_thirdparty_infra_images`
  lessons; backward-compat fallback follows the `reference_mailservice_sqlite_pattern`
  no-silent-fallback discipline (inverted: explicit default IS allowed here for R7).
