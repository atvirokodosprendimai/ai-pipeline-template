---
title: "feat: non-goose agent executor — make the LangChain implementer actually implement"
type: feat
date: 2026-06-20
depth: deep
origin: none (diagnosis this session; convergence-stall layer 4 + strategic "build non-goose autobox")
---

# feat: non-goose agent executor

**Target files:** `pipeline/wgmesh_pipeline/langchain_agent/*`, a new prompt, a local replay
harness + tests. Deploys to the box via `update-pipeline-box` only after local proof.

## Summary

Strategic direction (operator, 2026-06-20): **goose stays as KTLO** (it converges today —
opened real impl PR #785), **all new work targets the non-goose executor.** The non-goose path
(`EXECUTOR=langchain`, `langchain_agent/runner.py`) is wired and its tools/loop work, but it
**does not implement**: a live run produced 844 input tokens, no file reads, an empty diff, and
`implement.py` raised `goose implementation produced no tree changes`.

**Diagnosed root cause:** the agent is driven like a goose *recipe*, not an autonomous agent. It
is handed `pipeline/recipes/wgmesh-implementation.yaml`, whose step 6 literally says
*"Run exactly: `git add -A && git reset … && git diff --cached > diff_file`"*. The ReAct agent
latches onto that literal command, runs it **first**, skips the actual implementation (steps 1–5),
and writes an empty diff. The runner then accepts it because completion is **existence-of-diff-file**
(`runner.py` post-loop checks `output_path.exists()`), not real tree changes. The system prompt
reinforces this — *"use the tools to write the requested expected output before finishing."* The
tools (`read_file`/`write_file`/`edit_file`/`run_bash`/`search`) are fine; the **driving** is wrong.

This plan makes the non-goose executor actually implement: an agent-native task prompt (do the
work, edit files, verify), a completion contract based on **real workspace changes** rather than a
diff-file artifact, agent-trace observability, and a **local replay harness** so we can iterate the
agent without the box (goose keeps the lights on throughout).

## Problem Frame

- **Observed:** `advance #N@spec_ready failed: goose implementation produced no tree changes`;
  `stage=implement tokens=844/34`; agent reads nothing, edits nothing.
- **Mechanism:** goose-shaped recipe + existence-only completion → agent games "produce the diff
  file" instead of implementing.
- **Constraint:** goose remains the live executor (`EXECUTOR=goose`) and the only converging path
  until this is proven. No box disruption; iterate locally.
- **Goal:** the LangChain agent reads the spec, edits real source via tools, verifies build/test,
  and the runner reports success **only when the workspace actually changed** — producing real
  impl PRs equivalent to goose's.

---

## Scope Boundaries

**In scope**
- `langchain_agent/runner.py` — completion contract, agent-trace logging, prompt wiring.
- A new **agent-native implement prompt** (not the goose recipe).
- A **local replay harness** + deterministic fake-client tests + an optional creds-gated real run.
- `langchain_agent/prompts.py` and `langchain_agent/tools.py` as needed.

**Out of scope**
- **Goose** (`goose/runner.py`, `recipes/`) — untouched; KTLO. Removed only after this is proven.
- The **merge model** (judge-gated automerge, drop reviewer-PAT) — its own separate program; this
  plan ends at "real impl PR opens," not at merge.
- The `EXECUTOR=langchain` production flip — gated behind local proof + a shadow/parallel pass.

### Deferred to Follow-Up Work
- Retire goose + recipe layer + reviewer-PAT (#1898) once the agent executor is proven in prod.
- Judge-gated automerge (the merge-side non-goose work).
- Model selection tuning for the agent (see Open Questions).

---

## Key Technical Decisions

- **KTD1 — Drive the agent, don't run a recipe.** Replace the goose recipe input for the langchain
  implement path with an **agent-native task prompt**: read the spec, read the real source the spec
  touches, **edit files with `edit_file`/`write_file`**, run `go build/test/vet`, iterate, then
  stop. No `diff_file`, no "Run exactly: <git command>" — those are goose packaging steps the agent
  games.
- **KTD2 — Completion = real workspace changes, not a diff artifact.** For the implement stage, the
  runner's success condition becomes "the agent stopped **and** the workspace has uncommitted
  changes" (git-dirty), instead of `output_path.exists()`. The diff is derived from git by
  `implement.py` (`_stage_impl_tree` + `git diff --cached`), which already exists — so the runner
  should hand back "the agent did work," and let `implement.py` own diff capture. This removes the
  gameable artifact and the existing `"no tree changes"` guard stays as the backstop.
- **KTD3 — Keep the runner/tools/loop; change the contract.** The ReAct loop, the tools, the
  context-bounding (#1886) all stay. This is a prompt + completion-contract change, not a rewrite.
- **KTD4 — Local replay harness is the dev loop.** A standalone entrypoint runs
  `LangchainAgentRunner` against a real spec + a checkout and dumps the agent trace, so we iterate
  without touching the box. Deterministic tests use a **recorded/fake tool-calling client** (no
  network); a real-LLM run is **opt-in, creds-gated** (`ZAI_API_KEY`).
- **KTD5 — Agent-trace observability is permanent.** Per-iteration tool-call logging (already added)
  stays in `runner.py` — both for local replay and for the eventual shadow run on the box.
- **KTD6 — Prove before flip.** `EXECUTOR=langchain` goes live only after: (a) local replay shows
  real edits + passing `go build` on ≥1 real spec, and (b) a shadow/parallel pass on the box. Goose
  stays the floor until then.

---

## High-Level Technical Design

```
spec_ready issue
   │
   ▼  implement_node (real_path)
   ├─ materialize spec, prepare workspace (unchanged)
   ▼
LangChain agent (run_recipe → run_task):
   system: "You are an autonomous coding agent. IMPLEMENT the spec by editing files."
   task:   read spec → read source → edit_file/write_file → run_bash(go build/test/vet) → iterate
   loop:   bounded tool output (#1886), per-iter trace log
   STOP when: model emits no tool call  (NOT "a diff file exists")
   │
   ▼  success contract = workspace is git-dirty (real edits)   ← KTD2
implement_node: _stage_impl_tree + git diff --cached → derive diff → commit → open PR
   (existing "no tree changes" guard remains the backstop)
```

Contrast with today: the agent was told to *produce `diff_file`*; it produced an empty one and the
runner accepted existence. New: the agent is told to *edit the code*; success is measured by the
code actually changing.

---

## Implementation Units

### U1. Agent-trace logging (observability) — DONE on branch

- **Goal:** Surface the per-iteration tool sequence so agent behavior is explainable.
- **Requirements:** KTD5.
- **Dependencies:** none.
- **Files:** `pipeline/wgmesh_pipeline/langchain_agent/runner.py` (already edited).
- **Approach:** `_LOGGER.info("agent trace stage=%s iter=%d tools=%s text_len=%d", …)` each
  iteration. Full untruncated results still only in `raw_log`.
- **Test scenarios:** existing runner tests still pass; a fake-client run emits one trace line per
  iteration naming the tools called.
- **Verification:** local replay (U2) prints `tools=['run_bash']` for the current broken behavior,
  confirming the diagnosis.

### U2. Local replay harness + deterministic tests

- **Goal:** Run and iterate the executor off-box.
- **Requirements:** KTD4.
- **Dependencies:** U1.
- **Files:**
  - `pipeline/wgmesh_pipeline/langchain_agent/replay.py` (new entrypoint:
    `python -m wgmesh_pipeline.langchain_agent.replay --spec <path> --repo <path>`)
  - `pipeline/tests/test_langchain_agent_replay.py`
- **Approach:** Build a `LangchainAgentRunner` against a given spec + checkout, run it, print the
  agent trace + final result (ok, output, tree-dirty). Deterministic tests inject a **fake
  tool-calling client** that scripts a known tool sequence (e.g. read_file→edit_file→stop) and
  assert the runner drives it correctly. A real-LLM path is opt-in behind `ZAI_API_KEY` (skipped in
  CI).
- **Test scenarios:**
  - Fake client that edits a file then stops → runner reports success with a dirty workspace.
  - Fake client that only runs `run_bash` (the current bug) → runner reports **no real changes**
    (post-KTD2), reproducing the live failure deterministically.
  - Real-LLM test is `skipif` no `ZAI_API_KEY`.
- **Verification:** `pytest test_langchain_agent_replay.py` green; `replay.py` runs locally and
  prints a trace.

### U3. Agent-native implement prompt

- **Goal:** Drive real implementation, not diff-file production.
- **Requirements:** KTD1.
- **Dependencies:** U2 (to validate the prompt drives edits).
- **Files:**
  - new `pipeline/wgmesh_pipeline/langchain_agent/prompts.py` task template (or a new
    `recipes/wgmesh-implementation-agent.md` consumed only by the langchain path)
  - `langchain_agent/runner.py` (wire the implement stage to the agent prompt, not the goose recipe)
  - `pipeline/tests/test_langchain_agent_prompts.py`
- **Approach:** Author a system+task prompt that (a) names the deliverable as *edited source +
  passing build*, (b) instructs read-spec → read-source → edit → verify → stop, (c) explicitly says
  **do not** write a diff file or run packaging git commands — the pipeline derives the diff. Keep
  the Go project context + "verify types exist before referencing." Route the implement stage to
  this prompt; spec/triage stages unchanged.
- **Test scenarios:**
  - Rendered prompt contains edit-files instructions and **omits** the `diff_file` / "Run exactly"
    git step.
  - Required params resolve; missing params raise `PromptRenderError`.
  - (Via U2 real run, creds-gated) the agent calls `read_file` + `edit_file`/`write_file`, not just
    `run_bash`.
- **Verification:** local replay with the new prompt shows the agent reading the spec and editing
  files; token count rises from 844 into a real implementation range.

### U4. Completion contract = real workspace changes

- **Goal:** Success only when the agent actually changed code.
- **Requirements:** KTD2.
- **Dependencies:** U2, U3.
- **Files:**
  - `langchain_agent/runner.py` (implement-stage completion)
  - `pipeline/tests/test_langchain_agent_runner.py`
- **Approach:** For the implement stage, replace the `output_path.exists()/size>0` success signal
  with a **git-dirty check** of the workspace (or hand back "agent finished" and let
  `implement_node`'s existing `git diff --cached --quiet` guard be the sole authority — preferred,
  fewer moving parts). Revisit the #1886 U2 finish-on-expected-output so it doesn't early-exit on a
  diff artifact for this stage. Preserve all other failure semantics (timeout, max-iter,
  prompt-render error, unknown tool).
- **Test scenarios:**
  - Agent edits a file then stops → success.
  - Agent stops with no edits (clean workspace) → failure (`no changes implemented`), not success.
  - Pre-existing stale diff file present but no real edits → **failure** (closes the existence-only
    hole and the U2 stale-file regression flagged in #1886's risks).
  - Timeout / max-iter / unknown-tool failures unchanged.
- **Verification:** the deterministic "only run_bash, no edits" replay now returns failure (not the
  silent ok→"no tree changes" path); a real edit returns success.

### U5. Validation gate (local proof + shadow), then flip

- **Goal:** Prove the agent executor produces real impl PRs before any production flip.
- **Requirements:** KTD6.
- **Dependencies:** U3, U4.
- **Files:** none (process) — a documented run + a control-replay note in the plan/PR.
- **Approach:** (1) Local replay against ≥1 real requeued spec (creds-gated) → assert real edits +
  `go build ./...` clean. (2) Shadow/parallel on the box: run the agent executor on one issue
  without flipping the global `EXECUTOR`, compare its diff to goose's. (3) Only then flip
  `EXECUTOR=langchain` via set-box-env, watch the journal for a real `fix:` PR. Goose stays the
  floor; revert on any regression.
- **Test scenarios:** `Test expectation: none — validation/process unit.`
- **Verification:** a real `fix: Issue #N` PR opened by the agent executor with a non-empty,
  build-clean diff; tokens in a real range; trace shows read+edit calls.

---

## Risks & Dependencies

- **R1 — Model capability.** GLM-4.7 (current implement model) may be too weak to drive an agentic
  edit loop reliably even with a good prompt. Mitigation: the harness (U2) lets us A/B models
  cheaply; route the implement stage to a stronger model if needed (see Open Questions). Don't
  conclude "agent can't implement" until tested with a capable model + the new prompt.
- **R2 — Verification cost/time.** `go build/test/vet` inside the agent loop is slow and
  token-heavy; bounded tool output (#1886) helps. Cap verify iterations; the wall-clock limit
  already exists.
- **R3 — Don't disturb goose.** All iteration is local/shadow; the global `EXECUTOR` stays goose
  until U5 passes. No box flip in this plan's main path.
- **Dependency:** local real runs need `ZAI_API_KEY` (and possibly a stronger model's creds). If
  unavailable locally, U3/U5 real-validation happens in a box shadow run instead — note the gap.

## Resolved Decisions (operator, 2026-06-20)

- **Agent model(s):** test **DeepSeek (metered, cheap)** and **MiniMax (flat-rate)** — move off
  GLM-4.7 (it produced 844 tokens / no edits); skip frontier unless both fail. Route the implement
  stage to these via the model-routing layer (`MODEL_REGISTRY`/`STAGE_ROUTING`).
- **Run env for real experiments:** **box shadow run** — execute the agent executor on the box
  (has creds) against one issue WITHOUT flipping global `EXECUTOR`; goose stays live. No local key.

## Open Questions (resolve during implementation)

- **New recipe file vs inline prompt?** A `recipes/wgmesh-implementation-agent.md` keeps prompts
  editable without code changes; an inline template is simpler. Pick during U3.
- **DeepSeek vs MiniMax** — decide from the shadow A/B (real edits + `go build` clean + cost).

## Verification (end-to-end)

1. Unit suites green (replay, prompts, runner).
2. Local replay: agent reads spec + edits files + `go build` clean on a real spec.
3. Box shadow run matches goose-quality diff.
4. Flip `EXECUTOR=langchain` → real `fix:` PR opens; tokens in a real range; trace shows read+edit.
5. Only after sustained green: retire goose (separate follow-up).
