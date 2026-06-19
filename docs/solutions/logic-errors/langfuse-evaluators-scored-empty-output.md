---
title: "Langfuse LLM-judge evaluators scored an empty field on every real generation"
category: logic-errors
date: 2026-06-19
tags: [langfuse, evaluators, tracing, observability, llm-as-judge, wired-but-off-path]
related_issues: []
severity: high
component: evals
---

# Langfuse LLM-judge evaluators scored an empty field on every real generation

## Problem

All six Langfuse LLM-as-judge rules (`growth_issue_quality`, `impl_faithfulness`,
`public_safety_pass`, `no_component_paywall`, `open_source_default`,
`redo_of_shipped_capability`) map `{{output}}` ← observation `output` and filter
`type=GENERATION`. They fired and produced scores, so the deployment *looked* healthy
— but the judges scored an **empty field**. Confirmed live: a dumped GENERATION's
`output` was a judge replying *"I need to see the actual text content to evaluate it.
You've provided the instructions/rules for the check, but not the text to be reviewed."*

Two distinct defects:

1. **Empty `{{output}}`.** The box's only generation-emit path, `emit_generation`
   (`pipeline/wgmesh_pipeline/tracing.py`), wrote GENERATION observations with `name`,
   `model`, and token-count `usage_details` only — **no text**. The actual stage text
   lived on the `trace_node` **span** (`as_type="span"`), which the `type=GENERATION`
   filter does not match. So `{{output}}` was empty; NUMERIC judges defaulted high
   (the redo rubric's "names no capability → NOT APPLICABLE → 1.0"), so the redo
   evaluator could never flag a real redo.
2. **Recursive scoring.** The eval worker's own judge LLM calls are logged as
   GENERATIONs named `ChatAnthropic`, matched `type=GENERATION`, and were re-scored by
   all six rules — the judges scoring each other's calls, inflating the score counts
   with meaningless self-evaluations.

This is the field-level form of the wired-but-off-path trap: "firing" ≠ "scoring real
content." The fix it took was tracing the judge's `{{var}}` to the exact observation
field that carries it, on a *real* trace.

## Root cause

`emit_generation` was post-hoc *usage* telemetry — the goose and langchain runners call
it once per stage with only token totals — never the LLM-call site with the completion
text. The eval rules were pointed at it anyway, and nothing distinguished box
generations from the eval worker's own judge generations.

## Fix

- **Enrich generations with deliverable text.** `emit_generation` gained optional
  `input`/`output` text params plus a `metadata={"source":"box","stage":...}` marker.
  The runners thread the stage deliverable: the langchain completion string, and — for
  the live goose executor — the written/salvaged `output_path` content (goose usage is
  token-only with no completion text, so the deliverable file is the real output). Emit
  fires once per non-timeout run: usage-only on failure/timeout, usage+deliverable on
  success.
- **Exclude judge self-calls.** The shared rule filter adds `name "none of"
  ["ChatAnthropic"]` (the eval worker's judge generations), keeping every box
  `<stage>-llm` generation. Confirmed live: the unstable eval-rule API accepts the
  `name` column + `none of` operator (6/6 rules applied 200 OK).
- **`verify` surfaces the box-generation output state** so a regression to empty output
  reads as "enrichment not live on the box," not a generic WAIT.

## Deferred / residual

- The redo and growth judges expect a *proposed issue*, produced by the GHA
  observation-loop (raw `curl`, uninstrumented). After this fix they score the box's
  stage deliverable (triage/spec/impl text), not issue proposals. Instrumenting the
  observation-loop is follow-up.
- Live confirmation that box generations carry text requires the box to deploy this
  tracing change (it runs the legacy goose executor); `verify` distinguishes
  not-yet-deployed from fixed.
- The parked redo-evaluator dataset benchmark (`docs/plans/2026-06-19-003-...`) resumes
  once generations carry real text in the shape prod emits.
