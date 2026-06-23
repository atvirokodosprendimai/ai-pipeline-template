# Roadmap — full LangChain + LangGraph + Langfuse triad

**Date:** 2026-06-23 · **Owner:** pipeline · **Status:** proposed
**Goal:** every agent call runs on **LangChain**, orchestrated by a **LangGraph** state
graph, fully traced + scored by **Langfuse** — one consistent, observable agent runtime,
no Goose remnants, no blind spots.

---

## Where each layer stands (2026-06-23)

- **LangChain (`EXECUTOR=langchain`)** — LIVE on the box for the build lane (triage→spec→impl→
  review run the in-process LangChain agent). The `ChatAnthropic` client timeout was just
  raised 60s→600s (PR #1985). **Gap:** the **observation assess** (`observation_gather.py`) and
  **decision proposal** (`decision_lane/proposal_runner.py`) recipes still construct `GooseRunner`
  directly — two surfaces bypass the configured executor.
- **LangGraph (`GRAPH_IMPL`)** — `graph/build_lg.py` (`build_state_graph`, `StateGraph`) is built
  and `build.py` dispatches to it when `graph_impl=langgraph`; parity tests exist. **Gap:** the box
  defaults to `legacy` — LangGraph is built + tested but **not cut over**.
- **Langfuse** — LIVE: `init_tracing` runs, the `langfuse.langchain.CallbackHandler` is imported,
  manual `trace_node` wraps each graph node, and impl-judge scores + evaluators run. **Gap:** the
  `CallbackHandler` is constructed but is **likely not threaded into the agent's `callbacks=`**, so
  per-LLM-call / per-node auto-tracing isn't active — only the coarse manual `trace_node`.

**Net:** LangChain ~80%, LangGraph ~0% live (built), Langfuse ~60% (tracing live, auto-trace not
wired). The pieces exist; the work is completion + cutover + wiring, not greenfield.

---

## Phase 0 — Verify the live truth (before building)

Cheap probes so the roadmap acts on facts, not assumptions:

- **GRAPH_IMPL on the box** — confirm whether the box runs `legacy` or `langgraph` (the journal
  shows `executor=langchain` but not the graph impl). Likely `legacy`.
- **Langfuse callback wiring** — confirm whether `CallbackHandler` is actually passed to the
  LangChain agent's `.invoke(..., config={"callbacks": [...]})`, or only constructed. Determines
  whether auto-tracing is on.
- **Goose-surface inventory** — confirm the only non-executor Goose callers are observation +
  decision (grep `GooseRunner(`), so Phase 1 scope is exact.

---

## Phase 1 — LangChain: one executor everywhere

Move the last two Goose surfaces onto the configured executor so the whole pipeline runs one agent
runtime.

- **Decision proposal** → route `proposal_runner.py` through `build_executor(config)` instead of
  `GooseRunner` directly (I wired it to Goose; it should honor `EXECUTOR`).
- **Observation assess** → run the assessment recipe through the configured executor. (Bigger: the
  assess recipe is prompt-heavy; verify the langchain agent produces the same strict-JSON
  assessment the goose recipe does, behind a parity check before cutover.)
- **Outcome:** `EXECUTOR=langchain` means *every* LLM task — build, observation, decision — runs on
  LangChain. Goose becomes the fallback executor, not a parallel hardcoded path.
- **Risk:** the observation/decision recipes were tuned for Goose's output discipline; a langchain
  parity gap could regress assessment quality. Gate each on a shadow parity check.

## Phase 2 — LangGraph: cut over the stage graph

Make `GRAPH_IMPL=langgraph` the live graph.

- **Shadow-prove parity** — run the langgraph graph against the legacy graph on the same inputs
  (the parity tests are the seed); confirm identical stage transitions + outputs on a real cycle.
- **Flip** `GRAPH_IMPL=langgraph` via `set-box-env`, restart, verify a real issue flows
  triage→spec→impl→review on the langgraph graph. Rollback = flip back to `legacy`.
- **Then exploit what legacy can't do** — once live, use LangGraph's real powers the hand-rolled
  graph lacks: checkpointed state (resume a stalled run instead of restarting), conditional edges
  (route by risk tier / classification), built-in retries on a node, and human-in-the-loop
  interrupts (the decision lane's consent gate expressed as a graph interrupt rather than a poll).
- **Outcome:** the pipeline's control flow is a declarative, checkpointable graph — not a poller
  state machine.

## Phase 3 — Langfuse: auto-trace + score the whole graph

Wire Langfuse so every node + generation + tool call is captured, and the existing evals attach.

- **Thread the `CallbackHandler`** into the langchain/langgraph runner's invoke config
  (`callbacks=[handler]`) so a single run becomes one Langfuse trace with nested spans per node /
  LLM call / tool. Replace (or layer over) the coarse manual `trace_node`.
- **Attach scores to traces** — ensure impl-judge faithfulness/safety + the decision/observation
  scores land on the right trace/observation id (not orphaned), so a trace shows *what ran* AND
  *how good it was* in one view.
- **Datasets + eval loop** — promote recurring inputs (specs, proposals) into Langfuse datasets and
  run the evaluators against them, closing the observe→score→improve loop.
- **Outcome:** full per-node observability of the langgraph runtime + grading, the canonical
  langgraph+langfuse payoff.

---

## End state

```
EXECUTOR=langchain   — every agent call (build / observation / decision) on one LangChain runtime
GRAPH_IMPL=langgraph — stages as a checkpointed, conditional, interruptible state graph
Langfuse             — one nested trace per run, every generation + score captured, eval loop closed
```

One agent runtime, one orchestration model, one observability plane — no Goose remnants, no manual
trace gaps, no built-but-dark capabilities.

## Sequencing & risk

P0 (verify) → P1 (executor completeness, parity-gated) → P2 (langgraph cutover, shadow-proven) →
P3 (langfuse auto-trace + evals). P1 and P3's callback-wiring are independent and can overlap; P2
should follow P1 (cut the graph over once one executor runs under it) and precede the deeper P3
auto-trace value (a langgraph run is what you most want auto-traced). Each cutover is a flag flip
with a flag-flip rollback — the established box discipline (`set-box-env` + shadow-prove).

**The provider stays flaky** — none of this fixes z.ai timeouts; it makes them *visible* (Langfuse)
and *recoverable* (LangGraph node retries + checkpoints). Resilience is a cross-cutting follow-up,
not a triad phase.
