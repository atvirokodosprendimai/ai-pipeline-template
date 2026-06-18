# Langfuse cookbook — applicable patterns

Date: 2026-06-18
Source: https://github.com/langfuse/langfuse-docs/tree/main/cookbook
Status: research note — no code applied (target chosen later)

R&D survey of the Langfuse cookbook, mapped to this pipeline's three Langfuse
touchpoints:

- Online LLM-as-judge evaluators — `pipeline/evals/setup_langfuse_evaluators.py`
- Offline deterministic evals — `pipeline/evals/eval_gate.py`, `eval_spec.py`, `run_evals.py`
- LangGraph box tracing — `pipeline/wgmesh_pipeline/tracing.py`, `observation_gather.py`

---

## 1. External evaluation pipeline

Cookbook: `example_external_evaluation_pipelines.ipynb`. Three steps, run in
CI/cron: **fetch traces → run eval → push scores back**.

```python
from langfuse import get_client
langfuse = get_client()

# fetch
batch = langfuse.api.trace.list(
    tags="ext_eval_pipelines",
    page=n, limit=10,
    from_timestamp=five_am_yesterday, to_timestamp=five_am_today,
).data

# eval + push (persist reasoning alongside the score for interpretability)
for trace in batch:
    result = my_eval(trace)            # any logic — deterministic or LLM
    langfuse.create_score(
        trace_id=trace.id,
        name="tone", value=result["score"], comment=result["reason"],
    )
```

Batch with checkpoints to resume on failure; parallelize batches in production.

**Our gap / fit.** Our offline `eval_gate`/`eval_spec`/`run_evals` produce metrics
but never attach to box traces — the two eval surfaces stay disjoint (STRATEGY
flags unifying them). A thin `create_score` push would surface deterministic
gate/spec verdicts on the same traces the online judges score. Additive,
low-risk; moderate ROI because the online evaluation-rules already score live
generations.

---

## 2. Prompt management

Cookbook: `prompt_management_langchain.ipynb`. Prompts versioned in Langfuse,
fetched at runtime, linked to generations.

```python
prompt = langfuse.get_prompt("box-triage")
text = prompt.compile(**vars)   # variable substitution; ties traces to a version
```

**Our gap / fit.** The box's own triage/spec/impl prompts are hardcoded strings
in `observation_gather.py` — moving them to `get_prompt()` allows UI versioning
and prompt-level trace analytics. Note: the four **judge** prompts already live
inside Langfuse evaluator definitions (versioned there on re-create), so
prompt-management is redundant for the judges — it only helps the box's
generation prompts.

---

## 3. LangGraph `CallbackHandler` (highest value)

Cookbook: `integration_langgraph.ipynb`. The **recommended** tracing path for
LangGraph is the callback handler, not hand-rolled spans.

```python
from langfuse.langchain import CallbackHandler

graph.stream(state, config={"callbacks": [CallbackHandler()]})

# multi-agent: share one trace_id (via get_client()) to group agent spans in one trace
```

Requires Python ≥ 3.11.

**Our gap / fit.** `tracing.py` hand-rolls `start_span` / `start_observation`.
That is exactly the surface that broke twice on SDK bumps (v4 renamed
`start_span` → `start_observation`; a later test needed `importorskip`). The
`CallbackHandler` is maintained against the SDK and would eliminate that
recurring break class — at the cost of touching all box observability, so it
needs live-box verification (a real trace landing in Langfuse) before trusting
it. Highest value, highest risk.

---

## Recommendation

If/when applying, prioritize **#3 (CallbackHandler)** — it removes a recurring
bug class rather than adding surface area — gated behind a live-box trace check.
**#1 (external-eval scores)** is the safe additive follow-up that unifies the
offline and online eval views. **#2 (prompt management)** is lower priority and
only worthwhile for the box's generation prompts, not the judges.
