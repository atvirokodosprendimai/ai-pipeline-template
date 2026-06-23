---
date: 2026-06-23
topic: lang-triad-cutover
---

# LangChain / LangGraph / Langfuse triad — completion & cutover

## Summary

Finish and cut over the agent runtime so every LLM task runs one stack: the
configured executor (LangChain) everywhere, a live LangGraph state graph with its
full capability set switched on, and Langfuse capturing one nested trace per run
plus scores and a dataset eval loop. The pieces exist; the work is completion,
cutover, and wiring — not greenfield. Each cutover is shadow-proven then
human-flipped on the box, the same `set-box-env` discipline already used for
merge-lane-heal and the Quackback cutover.

---

## Problem Frame

The agent runtime is three layers at three different states of completion, and the
gaps compound into drift and blind spots.

LangChain is live for the build lane (triage→spec→impl→review) via the in-process
executor, but two surfaces — observation assess (`observation_gather.py:183`) and
decision proposal (`decision_lane/proposal_runner.py:29`) — construct `GooseRunner`
directly and bypass the `EXECUTOR` setting. The pipeline therefore runs two agent
runtimes at once, and the observation/decision paths can't inherit executor-level
fixes.

LangGraph is built and parity-tested (`graph/build_lg.py`, dispatched by `build.py`
when `graph_impl == "langgraph"`) but the box defaults to `legacy` — the
hand-rolled poller state machine. The declarative graph's real powers (checkpointed
resume, conditional edges, node retries, human-in-the-loop interrupts) sit dark.

Langfuse tracing initializes and the `CallbackHandler` is constructed, but it is
threaded into the LangGraph invoke path only (`build_lg.py:45`), not the legacy
path. Because the box runs legacy, per-node auto-tracing is effectively off — only
the coarse manual `trace_node` fires. Observability has structural blind spots.

The cross-cutting pain underneath all of this is a flaky provider: z.ai timeouts hit
at the SDK boundary with no agent-loop backoff. The triad doesn't fix the provider,
but it makes those failures *visible* (Langfuse) and *recoverable* (LangGraph node
retries + checkpoints).

---

## Key Decisions

- **All three layers, full P1–P3 in one plan.** Each layer earns its place; this is
  not a pick-the-cheap-win exercise. The end state is one executor, one orchestration
  model, one observability plane.

- **Full exploit at the LangGraph cutover, not flip-only.** When LangGraph goes live,
  wire its full capability set in the same plan: node retries, checkpointed resume,
  conditional edges (route by risk tier / classification), and the decision-lane
  consent gate expressed as a graph interrupt. Retries and checkpoints are nearly free
  at cutover time and awkward to bolt on later; they are also the capabilities that
  most justify the migration.

- **Resilience is in scope via node retries + checkpoints — not a follow-up.** The
  roadmap framed provider resilience as cross-cutting follow-up work. Because
  LangGraph's retry/checkpoint capability directly survives z.ai timeouts, that
  capability ships with P2. A deeper provider resilience layer (circuit-breaker,
  SDK-level backoff) stays out — see Scope Boundaries.

- **Shadow-prove then human-flip every surface; no automated blocking gate.** Run the
  new path in shadow on each surface, review the journal/diffs, flip the flag manually
  when it looks right. The established box discipline (`set-box-env` + shadow) is the
  control, consistent with the merge-lane-heal and Quackback cutovers. This also
  sidesteps the parity-anchor asymmetry: `observation_gather` emits strict 4-key JSON
  (`issues_to_create` / `issues_to_close` / `needs_human` / `prs_to_close`) that could
  be diffed structurally, but `decision_lane` returns free-form markdown with no
  structural anchor — a uniform human-flip gate fits both.

- **Decision proposal keeps its free-form output.** Cutting its executor over does not
  require restructuring the proposal format into JSON first.

- **Goose is demoted, not deleted.** It remains the fallback executor when
  `EXECUTOR != langchain`; the goal is to end the *parallel hardcoded* Goose paths,
  not remove the runtime.

- **Sequencing P0→P1→P2→P3 holds, and P2-before-P3 is reinforced.** Because the
  Langfuse handler already rides the LangGraph invoke path, flipping the graph live
  (P2) auto-lights per-node tracing. P3 then narrows mostly to attaching scores to the
  right trace ids and building the dataset eval loop.

---

## Requirements

### P0 — Verify live truth (recon, mostly done)

- R1. Confirm the box's graph impl (expected `legacy`) and the executor in use before
  any cutover. (Scout-confirmed: default `legacy`; build lane on `langchain`.)
- R2. Confirm the Goose-direct surface inventory is exactly observation assess and
  decision proposal. (Scout-confirmed: `observation_gather.py:183`,
  `decision_lane/proposal_runner.py:29`; `executor.py:54` honors `EXECUTOR`,
  default `goose`, fail-closed.)
- R3. Confirm the Langfuse `CallbackHandler` is wired to the LangGraph invoke path
  only and not the legacy path. (Scout-confirmed at `build_lg.py:45`.)

### P1 — One executor everywhere

- R4. Route decision proposal (`decision_lane/proposal_runner.py`) through
  `build_executor(config)` instead of constructing `GooseRunner` directly, so it
  honors `EXECUTOR`.
- R5. Route observation assess (`observation_gather.py`) through the configured
  executor, preserving the strict 4-key JSON assessment contract the goose recipe
  produces.
- R6. Each surface runs in shadow against its current Goose path; an operator reviews
  outputs before the flip. No automated blocking parity gate.
- R7. Outcome: `EXECUTOR=langchain` means every LLM task — build, observation,
  decision — runs on LangChain, with Goose as fallback only.

### P2 — LangGraph live, full capability set

- R8. Shadow-prove the langgraph graph against the legacy graph on the same inputs and
  confirm identical stage transitions and outputs on a real cycle, **before** any
  exploit feature is switched on.
- R9. Flip `GRAPH_IMPL=langgraph` via `set-box-env`, restart, and verify a real issue
  flows triage→spec→impl→review on the langgraph graph. Rollback = flip back to
  `legacy`.
- R10. Enable node retries and checkpointed resume so a provider timeout mid-run
  retries the node or resumes from the last checkpoint instead of restarting the run.
- R11. Add conditional edges that route by risk tier / classification where the legacy
  poller could only run a fixed sequence.
- R12. Express the decision lane's consent gate as a graph interrupt (human-in-the-loop)
  rather than a poll.
- R13. Each exploit feature (R10–R12) is switched on additively after the base-graph
  parity flip, each shadow-proven on its own before going live.

### P3 — Langfuse auto-trace, scores, eval loop

- R14. Confirm a live langgraph run produces one Langfuse trace with nested spans per
  node / LLM call / tool (the handler already rides the invoke path). Layer over or
  retire the coarse manual `trace_node`.
- R15. Attach existing scores (impl-judge faithfulness/safety, decision and observation
  scores) to the correct trace / observation id so a trace shows *what ran* and *how
  good it was* in one view — no orphaned scores.
- R16. Promote recurring inputs (specs, proposals) into Langfuse datasets and run the
  evaluators against them, closing the observe→score→improve loop.

---

## Key Flows

- F1. Executor surface cutover (P1, per surface)
  - **Trigger:** A Goose-direct surface is rerouted through `build_executor`.
  - **Steps:** Reroute the caller; run the configured executor in shadow alongside the
    live Goose path on real cycles; operator reviews the outputs (strict-JSON diff for
    observation, eyeball sample for decision); flip when satisfied.
  - **Rollback:** Revert the caller or set `EXECUTOR` back; Goose path is still present.
  - **Outcome:** Surface honors `EXECUTOR`.

- F2. LangGraph cutover with additive exploit (P2)
  - **Trigger:** Base-graph parity is proven on a real cycle.
  - **Steps:** Flip `GRAPH_IMPL=langgraph`; verify a real issue flows end-to-end;
    then switch on retries/checkpoints, then conditional edges, then the consent-gate
    interrupt — each shadow-proven before live.
  - **Rollback:** Flip `GRAPH_IMPL=legacy` (base), or disable the individual exploit
    feature.
  - **Outcome:** Control flow is a checkpointable, conditional, interruptible graph.

- F3. Timeout recovery (post-P2)
  - **Trigger:** A z.ai call times out mid-run.
  - **Steps:** The node retries per its retry policy; if still failing, the run
    checkpoints and can resume rather than restart from triage.
  - **Outcome:** Provider flakiness is recoverable, and the failure is visible in the
    Langfuse trace.

---

## Scope Boundaries

### Deferred for later

- A full provider-resilience layer beyond node retries/checkpoints — circuit-breaker,
  SDK-level backoff, smarter escalation. Node retries are the resilience ceiling for
  this work; the deeper layer stays the roadmap's cross-cutting follow-up.
- Restructuring decision proposal into structured/JSON output. Not required for the
  executor cutover.

### Outside this product's identity

- Deleting Goose. It stays as the fallback executor; the goal is to end parallel
  hardcoded Goose paths, not remove the runtime.

---

## Dependencies / Assumptions

- The langgraph parity-test pattern is the seed for R8, but a graph-level parity
  harness comparable to `spec_parity.py` may not yet exist and may need building —
  scout could not confirm a langgraph parity test. Treat as an open build item, not a
  given.
- Node retries / checkpointed resume assume LangGraph's checkpointer is configured with
  durable state the box can read across restarts; the storage backing is a planning
  decision.
- The consent-gate-as-interrupt (R12) intersects the decision lane / Quackback consent
  flow; its exact handoff is a planning concern, not resolved here.

---

## Outstanding Questions

### Resolve before planning

- None blocking. The three load-bearing product decisions (all-three scope, full
  exploit at cutover, shadow + human-flip) are settled.

### Deferred to planning

- Whether the manual `trace_node` is retired or kept as a coarse layer over the
  auto-trace (R14).
- The checkpointer storage backend and resume semantics (R10).
- The conditional-edge routing keys — which risk tiers / classifications drive which
  branches (R11).
- Whether a graph-level parity harness is built or parity is proven by journal review
  on a real cycle (R8).

---

## Sources / Research

- Grounding dossier (this brainstorm): `/tmp/compound-engineering/ce-brainstorm/lang-triad/grounding.md`
- Roadmap: `docs/roadmaps/2026-06-23-lang-triad-roadmap.md`
- Goose-direct callers: `observation_gather.py:183`, `decision_lane/proposal_runner.py:29`
- Executor selection: `executor.py:54` (`EXECUTOR` env, default `goose`, fail-closed)
- Graph dispatch: `build.py` (`graph_impl`), `graph/build_lg.py` (`build_state_graph`)
- Langfuse wiring: `tracing.py:164` (handler construction), `build_lg.py:45` (handler
  on invoke path)
- Recent provider-timeout fix: PR #1985 (`ChatAnthropic` timeout 60s→600s)
