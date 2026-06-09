---
title: "Goose weak model prints spec to stdout instead of writing the file"
date: 2026-06-09
category: runtime-errors
module: pipeline/wgmesh_pipeline/goose
problem_type: runtime_error
component: tooling
symptoms:
  - "`empty output guard fired for /opt/wgmesh-checkout/specs/issue-651-spec.md` -> RuntimeError: goose spec failed, every poller tick"
  - "goose exits 0 with the full spec markdown in stdout but the expected output file is never created"
  - "200 pipeline unit tests stay green while the live spec stage fails on every box tick (zero spec PRs)"
  - "goose raw_log contains no tool call -- only printed markdown (no developer write-tool invocation)"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags: [goose, glm-4.6, z-ai, headless-tool-calling, stdout-salvage, langgraph-pipeline, never-run-path, hollow-green]
---

# Goose weak model prints spec to stdout instead of writing the file

## Problem

The autonomous LangGraph pipeline's spec stage shells out to `goose run --no-session --recipe wgmesh-triage-spec.yaml` to have an LLM author a markdown spec file for a wgmesh issue. On the live box every spec stage failed: the weak model (glm-4.6 via z.ai) printed the spec as assistant text instead of calling Goose's `developer` write tool, so goose exited 0, stdout held the full markdown, the expected file was never created, and the empty-output guard failed the stage on every tick — producing zero spec PRs.

## Symptoms

- `empty output guard fired for /opt/wgmesh-checkout/specs/issue-651-spec.md`
- `RuntimeError: goose spec failed` (raised from `spec_node`, `pipeline/wgmesh_pipeline/graph/nodes/spec.py`)
- goose subprocess exit code `0` — no crash, no nonzero return to key off
- `raw_log` shows printed markdown in stdout and **no** tool-call invocation
- 200 unit tests green throughout; the failure only ever appeared on the live box

## What Didn't Work

The salvage fix was the **last** in a chain of spec-write failure modes, each surfaced only on the live box over ~2 days. Earlier mitigations were necessary but not sufficient — the model still refused to write:

1. **No `goose_runner` injected (the path was never built).** (session history) The first pipeline build left `spec_node` a no-op: it set `spec_path` in state but never invoked goose. First live signal was `spec_pr_node` running `git add specs/issue-540-spec.md` → `fatal: pathspec did not match any files`.
2. **`GOOSE_PROVIDER`/`GOOSE_MODEL`/`ANTHROPIC_HOST` env vars alone** did not initialize the z.ai provider for headless runs — goose loaded the recipe, echoed its description, and exited 0 silently (~3.4 min, no agent run). Provider/model had to be pinned **inside the recipe YAML** (`settings:`), not just in env.
3. **`GLM-4.7` as the model id** did not exist — goose loaded the recipe then no-opped. The working id is `glm-4.6`.
4. **Recipe without the `developer` builtin extension.** (session history) The box runs `CONFIGURE=false`, so no extensions exist unless the recipe declares them. Without `extensions: [{type: builtin, name: developer}]` the model had no filesystem write tool at all — it could only print.
5. **systemd `ProtectSystem=strict` without whitelisting the checkout path.** (session history) Once the developer extension was present, goose authored the spec but hit `Read-only file system (os error 30)` on `/opt/wgmesh-checkout`, silently fell back to writing `/tmp/issue-584-spec.md`, and the guard fired because it checks the `spec_file` path, not `/tmp`. Fix was a one-line `ReadWritePaths=/opt/wgmesh-checkout` addition.
6. **Recipe-level "write the file; do not only print" instruction.** Present in the prompt and ignored. With a working model, working provider, the developer extension, and a writable path, glm-4.6 *still* chose to emit the spec as conversational text rather than a `write_file` tool call.

Lesson: prompt instructions plus correct tool/model/path wiring do **not** guarantee a weak model emits via the tool channel in a headless run. You cannot make the deliverable contingent on the model choosing the right output path.

> Debug cost note (session history): each of these was diagnosed through a ~14-minute gitops loop (deploy → wait for box tick → read journal). Five redeploy cycles burned ~1.5 hours. Live goose-config issues are far cheaper to debug with interactive box shell access than through deploy cycles.

## Solution

A code-level salvage in `run_recipe` (`pipeline/wgmesh_pipeline/goose/runner.py`). When goose exits 0 but the expected output file is missing or empty, persist the model's stripped stdout to the path — gated on a threshold so a trivial acknowledgement line is *not* salvaged and a true no-op still fails loudly.

**Before** — single guard; a printed-only run is unrecoverable:

```python
if not output_path.exists() or output_path.stat().st_size == 0:
    return GooseResult(ok=False, ..., error=f"empty output guard fired for {output_path}", ...)
```

**After** — salvage block ahead of the guard:

```python
if not output_path.exists() or output_path.stat().st_size == 0:
    # Weaker models (glm-4.6 on z.ai) frequently PRINT the deliverable as their
    # assistant text instead of invoking the developer write tool. goose
    # `run --no-session` emits assistant text to stdout (diagnostics to stderr),
    # so salvage it: persist stdout to the expected path.
    salvaged = _strip_ansi(completed.stdout or "")
    if len(salvaged.strip()) >= _MIN_SALVAGE_CHARS:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(salvaged, encoding="utf-8")
        except OSError as exc:
            return GooseResult(ok=False, output_path=output_path, ...,
                error=f"empty output + salvage write failed for {output_path}: {exc}", ...)

if not output_path.exists() or output_path.stat().st_size == 0:
    return GooseResult(ok=False, ..., error=f"empty output guard fired for {output_path}", ...)
```

Supporting constant and helper:

```python
# A genuine spec/diff is KB-scale; a stray "done"/acknowledgement line is not --
# below this we still fire the empty-output guard so a true no-op fails loudly.
_MIN_SALVAGE_CHARS = 200

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

def _strip_ansi(text: str) -> str:
    """Drop terminal escape sequences goose may emit so the salvaged file is
    clean markdown, not color-coded console output."""
    return _ANSI_RE.sub("", text)
```

Shipped in PR #1592. Verified live: re-provision journal showed `advanced #652 triaged -> specced` and `#651 triaged -> specced` with no guard error.

## Why This Works

- **Dual output channel.** `goose run --no-session` writes assistant text to **stdout** and diagnostics to **stderr**. When the model prints rather than tool-calling, the full deliverable is sitting in `completed.stdout` — recoverable without re-running the (slow, paid) goose invocation.
- **Happy path untouched.** When the model *does* call the write tool, the file already exists and is non-empty, so the salvage block is never entered. The fix is purely additive and model-agnostic.
- **ANSI stripping** keeps the salvaged file clean markdown, not color-coded console bytes.
- **Threshold gate prevents junk salvage.** `_MIN_SALVAGE_CHARS=200` means a stray "done, no file written" (a real model behavior) is *not* written as a fake spec — the guard still fires and the stage fails loudly (Andon: a genuine no-op stops the line instead of producing a hollow success).

## Prevention

- **Test the real subprocess shape, not a mock that always cooperates.** The 200 green tests passed because the mocked goose subprocess either wrote the file or didn't — none exercised "exit 0, prints full markdown to stdout, writes nothing" against the real guard. This is a hollow-green (the Nth in this pipeline; sibling shapes: green-tests-rest-on-stubs, test-fakes-override-the-gate). The two new tests close the gap by reproducing the production failure mode:
  - `test_printed_only_spec_is_salvaged_from_stdout` — model prints an ANSI-wrapped KB-scale spec, no file written; asserts salvage succeeds, file exists, ANSI stripped.
  - `test_trivial_stdout_still_fails_guard_no_junk_salvage` — model prints a short acknowledgement; asserts the guard still fires and **no** file is written (threshold bites).
- **Don't trust recipe/prompt instructions to constrain weak models.** "Write the file; do not only print" was present and ignored. For weak/headless models, enforce the deliverable in code, not in the prompt.
- **Assert the deliverable exists, not just that the tool "ran."** A 0 exit code is not success for a file-producing agent; the artifact is the contract — key the guard on it.
- **When wiring a headless agent to author files, verify the whole write path at once**: provider/model pinned in the recipe (not just env), valid model id, the `developer` builtin extension declared, the target dir writable under systemd hardening (`ReadWritePaths`), repo_path pointing at the right working tree — and a code-level salvage for when the model prints anyway.

## Related Issues

- `docs/solutions/design-decisions/multi-model-routing.md` — sibling work, shares `pipeline/wgmesh_pipeline/goose/runner.py` (`build_goose_env`, stage-threaded `run_recipe`). Its escalate-on-fail ladder handles quality-gate rejections; it does **not** catch empty-output stage failures — this salvage is the remediation for the weak-model printed-spec case.
- GitHub issue #745 — "detect contradictions between green metrics and stuck-state evidence" (the hollow-green theme).
- GitHub issue #739 — propagate wgmesh e2e auto-verification fix to the meta-pipeline template (verification-gap adjacent).
- PR #1592 — the fix.
