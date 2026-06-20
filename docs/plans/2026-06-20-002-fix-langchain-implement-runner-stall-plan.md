---
title: "fix: LangChain implement runner — context runaway + no completion detection"
type: fix
date: 2026-06-20
depth: standard
origin: none (diagnosis from box journal; pulse 2026-06-20_02-27 followup #2 — convergence stall)
---

# fix: LangChain implement runner — bound context + finish on expected output

**Target file:** `pipeline/wgmesh_pipeline/langchain_agent/runner.py` (+ tests). Deploys to the
Hetzner box via `update-pipeline-box` after merge.

## Summary

The autobox convergence engine is stalled: **every spec→impl advance fails** with
`RuntimeError: langchain agent reached max iterations (25)` at
`graph/nodes/implement.py:55`. Box journal shows the implement agent burning **800K–1M input
tokens per attempt** (glm-4.7, tiny output) before hitting the cap. 17 growth issues
(#732/#734/#745/#752/#779…) are frozen at `spec_ready`; 0 product PRs merge.

Root cause is in the ReAct loop in `runner.py` (`run_recipe`):
1. **No context bounding** — every tool result (`read_file`, `run_bash`, `search` all return
   unbounded text) is appended verbatim as a `ToolMessage`; `messages` is never pruned, so
   context balloons to ~1M tokens. At that size glm-4.7 degrades and never emits a terminal
   (no-tool-call) message → loops to the cap.
2. **No completion-on-expected-output** — the runner only checks `output_path.exists()`
   *after* the loop ends (line 149). The recipe's job is to write the unified diff to
   `diff_file`; once it exists the work is done, but the runner keeps looping waiting for the
   model to volunteer a no-tool-call turn.
3. **Flat `MAX_ITERATIONS = 25`** — too tight for a real implementation, but raising it
   without (1) just burns more tokens.

The fix bounds tool-output size, finishes as soon as the expected deliverable is written, and
makes the iteration cap configurable with a higher default.

## Problem Frame

- **Observed:** `advance #<n>@spec_ready failed: langchain agent reached max iterations (25)`,
  repeating; `tracing generation emitted stage=implement model=glm-4.7 tokens=820606/674`.
- **Box is healthy** — ticking every ~5 min, IP 204.168.186.39; this is purely the implement
  executor.
- **Operator decision (2026-06-20):** stay on `EXECUTOR=langchain` (no goose revert); fix the
  runner.
- **Goal:** the implement agent completes a normal implementation well within the cap, with
  bounded context, and the spec→impl→PR→merge flow resumes.

---

## Scope Boundaries

**In scope**
- The ReAct loop in `pipeline/wgmesh_pipeline/langchain_agent/runner.py`: tool-output bounding,
  completion-on-expected-output, configurable iteration cap.
- Tests in `pipeline/tests/test_langchain_agent_runner.py`.

**Out of scope**
- The shadow-mode control-loop modules (`selfheal`/`supervisor` `*_LIVE` flags) — separate
  parked gate, not the convergence blocker.
- `observation` module `LLM assessment failed` — separate live-module error, own follow-up.
- The orphaned PR-merge lane (GHA `Bot PR Review and Merge` disabled) — relevant once impls
  start landing again; revisit after this fix produces real impl PRs.
- Goose executor path (`goose/runner.py`) — unchanged; operator chose to stay on langchain.
- Prompt/recipe wording (`wgmesh-implementation.yaml`) — only touch if testing shows the agent
  needs an explicit "write the diff then stop" instruction (see Open Questions).

### Deferred to Follow-Up Work
- Smarter context management (summarise old tool turns vs. truncate) if truncation proves
  insufficient.
- Per-tool output caps inside `tools.py` (vs. the single runner-side cap chosen here).

---

## Key Technical Decisions

- **KTD1 — Cap tool output at the runner chokepoint, not in each tool.** All tool results pass
  through one place (the `ToolMessage` append, runner.py ~117). Truncate there → executor-wide,
  one code path, tools stay pure. Head+tail truncation with an explicit
  `…[truncated N chars]…` marker so the model knows output was clipped.
- **KTD2 — Finish as soon as the expected output exists.** After each tool-dispatch round,
  check `output_path.exists()` and non-empty; if so, emit usage and return `ok=True`. The diff
  file is the deliverable contract (`implement_node` passes `expected_output=diff_rel`); its
  presence is a more reliable completion signal than the model volunteering no tool call.
- **KTD3 — Configurable cap, higher default.** Replace the flat `MAX_ITERATIONS = 25` with an
  env-driven value (default 40). Bounded context (KTD1) makes extra iterations cheap; the
  higher default gives real implementations room. Fail behavior on cap is unchanged.
- **KTD4 — Preserve all existing failure semantics.** Timeout, prompt-render error,
  output-never-written, unknown-tool — all keep their current `_result(ok=False, …)` returns.
  This fix only adds an earlier success path and bounds growth.

---

## High-Level Technical Design

The loop today (runner.py 79–167), with the two new behaviors marked ★:

```
while iterations < MAX_ITERATIONS:            # ← MAX_ITERATIONS now configurable (KTD3)
    if wall-clock exceeded: return fail
    ai_message = llm.invoke(messages)
    append ai_message; accumulate usage
    tool_calls = ai_message.tool_calls
    if not tool_calls: break                  # existing terminal signal
    for call in tool_calls:
        result = dispatch[name](**args)
        result = _bounded(result)             # ★ KTD1: head+tail truncate to budget
        append ToolMessage(result)
    if output_path exists and non-empty:      # ★ KTD2: deliverable written → done
        emit usage; return ok=True
else:
    return fail("reached max iterations")     # unchanged
# post-loop: existing output_path.exists() check unchanged
```

Completion priority: model-stops (existing `break`) OR deliverable-written (new) → success;
wall-clock / cap / no-output → failure (unchanged).

---

## Implementation Units

### U1. Bound tool-output size before appending to context

- **Goal:** Stop the ~1M-token runaway by truncating each tool result to a fixed budget before
  it enters `messages`.
- **Requirements:** KTD1. Root-cause fix for the context balloon.
- **Dependencies:** none.
- **Files:**
  - `pipeline/wgmesh_pipeline/langchain_agent/runner.py`
  - `pipeline/tests/test_langchain_agent_runner.py`
- **Approach:** Add a module-level budget constant (e.g. `MAX_TOOL_OUTPUT_CHARS`, ~16000) and a
  small pure helper `_bounded(text)` that returns text unchanged when within budget, else
  head + `…[truncated N chars]…` + tail. Apply it to `str(result)` at the single
  `ToolMessage(content=…)` site. Keep the full untruncated result in `raw_log` (observability),
  only the model-facing `ToolMessage` is bounded.
- **Patterns to follow:** existing helper style in runner.py (`_message_content`, `_result`);
  keep the helper pure and unit-tested.
- **Test scenarios:**
  - Tool result under budget → passed through unchanged into `ToolMessage`.
  - Tool result over budget → `ToolMessage.content` length ≤ budget (+marker), contains head and
    tail, contains the truncation marker with the dropped char count.
  - `raw_log` still records the full untruncated result (observability preserved).
  - Helper is pure: same input → same output, no side effects.
- **Verification:** Unit tests green; a simulated large `run_bash` output no longer grows the
  message context beyond the budget per tool call.

### U2. Finish as soon as the expected output is written

- **Goal:** Return success the moment the diff file exists, instead of waiting for the model to
  emit a no-tool-call turn.
- **Requirements:** KTD2. Removes the "never terminates" failure mode.
- **Dependencies:** U1 (same loop region).
- **Files:**
  - `pipeline/wgmesh_pipeline/langchain_agent/runner.py`
  - `pipeline/tests/test_langchain_agent_runner.py`
- **Approach:** After the `for call in tool_calls` dispatch round, add a check: if
  `output_path.exists()` and the file is non-empty, emit usage and `return _result(ok=True, …)`
  with the current `completion_text`/usage. Mirror the existing post-loop success branch
  (149–158) so the return shape is identical. Non-empty guard avoids finishing on a zero-byte
  placeholder.
- **Patterns to follow:** the existing post-loop `if output_path.exists()` success return
  (runner.py 149–158) and `_emit_usage` call ordering.
- **Test scenarios:**
  - Agent writes the expected output at iteration k < cap while still requesting tools → runner
    returns `ok=True` at iteration k; loop does not run to the cap. (Covers the live failure.)
  - Expected output written but empty (0 bytes) → does NOT early-return; loop continues.
  - Expected output never written, model keeps calling tools → still fails at the cap (unchanged).
  - Model stops with no tool calls and output exists → existing post-loop success path still
    works (no regression).
  - Usage/`raw_log` are emitted on the early-success path same as the post-loop path.
- **Verification:** A fake client that writes the diff file mid-loop then keeps calling tools
  yields `ok=True` without reaching the cap; existing runner tests still pass.

### U3. Make the iteration cap configurable with a higher default

- **Goal:** Give real implementations room now that context is bounded.
- **Requirements:** KTD3.
- **Dependencies:** U1, U2.
- **Files:**
  - `pipeline/wgmesh_pipeline/langchain_agent/runner.py`
  - `pipeline/tests/test_langchain_agent_runner.py`
- **Approach:** Resolve the cap from the environment (e.g. `LANGCHAIN_MAX_ITERATIONS`) with a
  default of 40, read once in `run_recipe` (mirror the env-reading discipline already used for
  the agent). Keep `MAX_ITERATIONS` as the default constant. Invalid/absent → default. The
  failure message keeps reporting the actual cap used.
- **Patterns to follow:** `_get_nonempty`/`_get_bool` env-reading style in `config.py`; keep the
  resolution local and fail-safe (bad value → default, never raise).
- **Test scenarios:**
  - Default (no env) → cap is 40.
  - Env override to a small value (e.g. 3) → loop caps at 3, failure message reports `(3)`.
  - Non-integer env value → falls back to default, no exception.
  - `Test expectation: none` for the constant rename itself — covered by the override tests.
- **Verification:** Override test drives the cap deterministically; default test confirms 40.

---

## Risks & Dependencies

- **R1 — Truncation hides needed detail.** If the agent genuinely needs a large file's full
  contents, head+tail truncation could drop the relevant middle. Mitigation: 16KB budget is
  generous for code files; the marker tells the model to narrow its next read (e.g. `search` or
  a ranged read) rather than re-dump. Deferred follow-up: summarise instead of truncate.
- **R2 — Early-exit on a partial diff.** If the recipe writes the diff file incrementally, the
  non-empty check could fire mid-write. Mitigation: the recipe writes the diff as its final
  step (per `implement_node` contract); the non-empty guard covers the common placeholder case.
  If observed, gate on a trailing-newline/size-stable check (follow-up).
- **R3 — Deploy step.** Code reaches the box via `update-pipeline-box` (not auto on merge).
  After merge, that workflow must run to pick up the fix; then watch the box journal for a clean
  `advance …@spec_ready` (no max-iter error).
- **Dependency:** none external; single module + its test file. No new pip deps (the box agent
  is langchain-based; no new imports needed beyond stdlib `os`).

## Open Questions (resolve at implementation)

- Does the agent reliably write `diff_file` as its final action, or does it sometimes narrate
  without writing? If U2 doesn't fully drain the cap failures in box validation, add an explicit
  "write the unified diff to {diff_file} then stop" line to `wgmesh-implementation.yaml`
  (out of current scope; note for the post-deploy check).

## Verification (end-to-end)

1. Unit suite green: `python -m pytest pipeline/tests/test_langchain_agent_runner.py -q`.
2. Merge → run `update-pipeline-box`.
3. Watch box journal (`diagnose-box-journal`): a spec_ready advance completes without
   `reached max iterations`; an `impl` PR (`fix: Issue #N`) opens; implement-stage token counts
   drop from ~1M to a bounded range.
4. Next pulse: seed product PRs begin merging; `aged_open_items` starts falling.
