# Runbook — Box Goose→LangGraph executor cutover (U6)

Created: 2026-06-19
Owner: operator (live box has a human in the loop for this rollout)
Plan: `docs/plans/2026-06-18-001-feat-box-langgraph-executor-migration-plan.md`

Ships U1–U5 to the **live** wgmesh-pipeline box in stages, each gated and
flag-reversible, then deletes the dead Goose path. Nothing here changes box
behavior until a flag is flipped — `EXECUTOR` defaults to `goose`, `GRAPH_IMPL`
defaults to `legacy`.

## What's already on main (behind flags)
- `EXECUTOR=goose|langchain` (default `goose`) — `build_executor` factory.
- `GRAPH_IMPL=legacy|langgraph` (default `legacy`) — `build_graph` dispatch.
- `LangchainAgentRunner` (ChatAnthropic tool agent), robust recipe→prompt loader,
  langgraph `StateGraph` (parity-tested), `CallbackHandler` on `StateGraph.invoke`.

## Flag → behavior matrix
| EXECUTOR | GRAPH_IMPL | Executor | Graph | Tracing |
|---|---|---|---|---|
| goose | legacy | Goose CLI | CompiledGraph | trace_node + emit_generation (current prod) |
| goose | langgraph | Goose CLI | StateGraph | CallbackHandler (graph) + emit_generation (goose tokens) |
| langchain | langgraph | LangChain agent | StateGraph | CallbackHandler (graph + generations) |

Set flags in the box env file (`/etc/wgmesh-pipeline/env`) and `systemctl restart`,
or pass via the deploy workflow's env. Rollback = restore the prior flag value +
restart (no image rebuild). Deploy infra auto-rolls-back on an unhealthy SHA
(`deployed_sha`).

---

## Pre-flight (once, before step 1)
- [ ] Confirm the box image includes the new base deps: `langgraph`, `langchain-anthropic`, `pyyaml`, and `langfuse` (trace extra). Rebuild via `build-pipeline-image.yml` from a main SHA ≥ `0396fef` (U5) and confirm the GHCR tag.
- [ ] Box Python is 3.11 (CallbackHandler requires ≥3.11) — already the Dockerfile base.
- [ ] **Live-verify risk (carry from U2):** the default client factory builds `ChatAnthropic(model=…, base_url=profile.host or config.anthropic_host, api_key=…)`. Confirm `base_url` is the correct kwarg for the installed `langchain-anthropic` version against the z.ai endpoint — verify on the FIRST real LangChain generation (step 2), not before. If wrong, the symptom is a connection/4xx on the first `langchain` spec call; fix the kwarg (`base_url` vs `anthropic_api_url`) and redeploy.
- [ ] Capture the **baseline** autonomous-ship-rate + lead-time from the current Goose+legacy box (STRATEGY metrics) so steps 2–3 have something to compare against.

---

## Step 1 — Shadow: GRAPH_IMPL=langgraph (executor still goose)
Goal: prove the StateGraph runs the box identically AND CallbackHandler spans land,
with zero behavior risk (Goose still does the work, shadow mode = no side effects).

1. Deploy with `EXECUTOR=goose`, `GRAPH_IMPL=langgraph`, `PIPELINE_MODE=shadow` (dispatch `deploy-pipeline-box.yml` with the U5 SHA).
2. **Verify ticking:** dispatch `diagnose-box-journal.yml`; confirm recent `tick` lines, no `tracing degraded` / `Langfuse init FAILED`, no tracebacks.
3. **Verify spans:** dispatch `langfuse-probe.yml` (ingestion health), then Langfuse UI → Traces: confirm **node spans** (triage/spec/spec_pr/implement/review) appear via CallbackHandler, grouped under `issue-<N>` sessions. Generations still come from Goose `emit_generation`.
4. **Gate:** box ticks green for a full cycle + spans visible. If the StateGraph misbehaves vs legacy, roll back `GRAPH_IMPL=legacy` + restart. **STOP if any failed action** (action-success KPI).

---

## Step 2 — Shadow-compare: EXECUTOR=langchain in spec-only
Goal: prove the LangChain agent produces work comparable to Goose, on the cheapest
stage, before any live merge depends on it.

1. Set `EXECUTOR=langchain`, keep `GRAPH_IMPL=langgraph`, `PIPELINE_MODE=spec-only`. Deploy.
2. **First-generation check:** confirm the first LangChain spec generation actually calls the model — watch the journal + Langfuse for a generation span with token usage. This is where the `base_url` kwarg risk (pre-flight) surfaces; fix + redeploy if it errors.
3. **Compare:** for the same issues, diff the LangChain-produced spec vs the Goose baseline (content quality, scope, token cost). Sample several issues.
4. **Gate:** LangChain specs are at least on par with Goose + generations trace cleanly. If worse, roll back `EXECUTOR=goose`; investigate prompt/tool gaps (U3 prompts, U2 tools) before retrying.

---

## Step 3 — Staged live
Goal: let the LangChain agent do real merges for a bounded slice, watching the
ship-rate, with instant flag rollback.

1. `EXECUTOR=langchain`, `GRAPH_IMPL=langgraph`, `PIPELINE_MODE=live`. Deploy.
2. Start narrow — one issue class / a few issues. Watch per the **action-success KPI** (every action must succeed) and the autonomous-ship-rate vs the step-0 baseline; watch escalations.
3. **Rollback trigger:** any regression in ship-rate, a spike in escalations, a bad merge, or a failed action → flip `EXECUTOR=goose` (instant) + restart; triage before retrying.
4. **Gate:** N days stable at-or-above baseline ship-rate, no live defects, traces complete (node spans + generations grouped per issue).

---

## Step 4 — Cleanup (only after step 3 is durably stable)
Delete the dead Goose path and the legacy graph/tracing. Each is a normal
plan→Codex→review→ship slice (not part of the live runbook):
- [ ] Delete `GooseRunner` + `pipeline/recipes/*.yaml` (recipe text now flows through `prompts.py`/the agent) — or keep recipes as the prompt source and delete only the CLI runner. Decide at cleanup time.
- [ ] Delete `trace_node` + `emit_generation` + the per-stage tracing wiring (CallbackHandler now covers it). Make `GRAPH_IMPL=langgraph` the default, then remove the flag + `CompiledGraph`.
- [ ] Make `EXECUTOR=langchain` the default, then remove the flag + the `goose` branch.
- [ ] Drop the Goose CLI install from `pipeline/deploy/Dockerfile`.
- [ ] Fix the now-stale recommendation in `docs/research/2026-06-18-langfuse-cookbook-patterns.md` (CallbackHandler-first was correct only AFTER this migration; note it's now adopted).

## Verification surface (reference)
- `diagnose-box-journal.yml` — journal without restart (ticking, errors).
- `langfuse-probe.yml` — ingestion health.
- Langfuse UI — Traces (node spans, `issue-<N>` sessions), Observations (generations), Scores.
- STRATEGY metrics — autonomous-ship-rate, lead time, active stuck issues.

## Rollback summary
- StateGraph misbehaves → `GRAPH_IMPL=legacy`.
- LangChain agent misbehaves → `EXECUTOR=goose`.
- Both are env-flag flips + `systemctl restart` — no image rebuild. Infra auto-rolls-back an unhealthy `deployed_sha`.
