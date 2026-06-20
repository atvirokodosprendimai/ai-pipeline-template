---
title: "feat: impl-judge module — DeepSeek faithfulness + safety verdict (fail-closed)"
type: feat
date: 2026-06-20
depth: standard
origin: docs/plans/2026-06-20-005-feat-judge-gated-automerge-plan.md (U1, meta-repo slice)
---

# feat: impl-judge module (DeepSeek, fail-closed)

Meta-repo slice (U1) of the judge-gated-automerge plan
(`docs/plans/2026-06-20-005-feat-judge-gated-automerge-plan.md`). The wgmesh workflow wiring,
branch protection, box automerge, and reviewer-PAT retirement (that plan's U2–U5) are cross-repo
follow-ups, out of scope here.

## Summary

The non-goose autobox produces real `fix:` PRs but they don't merge — the box's distinct-principal
gate needs an approval it can't supply. The chosen replacement is a **fail-closed judge CI check**:
GitHub auto-merge merges a PR only when its required checks (build + judge) pass. This slice builds
the **judge itself** as a standalone, importable, testable module: given a unified diff and the
issue spec, it scores **faithfulness** (does the diff implement the spec) and **public-safety** (no
secrets / PII / exact revenue figures) using **DeepSeek** (via OpenRouter), and exits non-zero on
FAIL **or any error/ambiguity**. The wgmesh GitHub Actions check will call this module; building it
in the pipeline repo keeps one rubric source of truth alongside the Langfuse evaluators it reuses.

## Problem Frame

- **Need:** an objective, synchronous merge gate — a script that says PASS/FAIL on `(diff, spec)`,
  fail-closed, runnable as a CI check.
- **Why DeepSeek:** a different model family from the GLM-5.2 implementer → genuine second opinion,
  cheap (metered, low-volume gating). (origin: `2026-06-20-005` KTD2.)
- **Goal:** `impl_judge` returns a clear verdict + reasons and an exit code a CI check can gate on;
  errors never pass-by-default.

---

## Scope Boundaries

**In scope**
- A self-contained `impl_judge` module: prompt assembly from the reused rubrics, a stdlib-only
  HTTPS call to OpenRouter/DeepSeek, verdict parsing, fail-closed exit-code mapping, a CLI
  entrypoint taking the diff + spec (+ issue number), and unit tests with a stubbed LLM.

**Out of scope (cross-repo follow-ups, origin 2026-06-20-005)**
- The wgmesh `impl-judge.yml` workflow + branch protection + auto-merge (U2/U3).
- The box automerge transition and reviewer-PAT retirement (U4/U5).
- Pushing the verdict to Langfuse as a score (deferred there).

---

## Key Technical Decisions

- **KTD1 — Fail-closed everywhere.** Missing diff, missing/empty spec, HTTP error, non-2xx,
  unparseable or ambiguous LLM response → exit non-zero (FAIL) with the reason printed. Only an
  explicit, parsed `PASS` on both dimensions → exit 0. (origin KTD3.)
- **KTD2 — Reuse the evaluator rubrics in place.** Lift the `impl_faithfulness` and
  `public_safety_pass` rubric text from `pipeline/evals/setup_langfuse_evaluators.py` (single
  source of truth) into the judge prompt — do not re-author criteria.
- **KTD3 — stdlib-only HTTPS, OpenRouter/DeepSeek.** Mirror the `urllib` + Bearer-auth, fail-closed
  pattern of `setup_langfuse_evaluators.py`. Read the key from env
  (`OPENROUTER_API_KEY`/`DEEPSEEK_API_KEY`). Send a browser-like `User-Agent` (Cloudflare-1010
  lesson). Cap/truncate the diff to bound tokens.
- **KTD4 — Structured, parse-strict verdict.** Ask DeepSeek for a small structured response
  (per-dimension PASS/FAIL + reason); parse strictly; any parse failure is fail-closed, not a
  guess.
- **KTD5 — Importable core + thin CLI.** A pure `judge(diff, spec, *, issue) -> Verdict` function
  (testable with an injected HTTP caller) plus a `main()` that reads inputs, prints the verdict,
  and maps to an exit code. Keeps tests network-free.

---

## High-Level Technical Design

```
CLI main():
  read --diff-file / --spec-file (+ --issue), env OPENROUTER_API_KEY
  → judge(diff, spec):
        guard: empty diff / empty spec → Verdict(FAIL, "missing diff|spec")   # fail-closed
        build prompt from faithfulness + public_safety rubrics (truncate diff)
        POST OpenRouter/DeepSeek (urllib, Bearer, UA header)
        non-2xx / network error → Verdict(FAIL, "<error>")                    # fail-closed
        parse structured verdict; parse error → Verdict(FAIL, "unparseable")  # fail-closed
        both dimensions PASS → Verdict(PASS) ; else Verdict(FAIL, reasons)
  → print verdict + reasons ; exit 0 iff PASS else 1
```

Exit-code contract (the CI-check surface): `0` = PASS, `1` = FAIL-or-error. There is no neutral.

---

## Implementation Units

### U1. Judge core — prompt, DeepSeek call, fail-closed verdict

- **Goal:** A pure `judge(diff, spec, *, issue, http_caller=...)` returning a `Verdict`
  (pass: bool, reasons: list[str]) with fail-closed semantics on every error path.
- **Requirements:** KTD1, KTD2, KTD3, KTD4, KTD5.
- **Dependencies:** none.
- **Files:**
  - `pipeline/evals/impl_judge.py`
  - `pipeline/tests/test_impl_judge.py`
- **Approach:** Define `Verdict` (frozen dataclass). `judge(...)` guards empty diff/spec
  (fail-closed), assembles a prompt from the faithfulness + public-safety rubrics (imported/lifted
  from `setup_langfuse_evaluators.py`), truncates the diff to a char budget with a marker, and
  calls an injectable `http_caller` (default: a stdlib `urllib` POST to OpenRouter with Bearer auth
  + `User-Agent`). Map provider/network/parse failures to `Verdict(pass=False, reasons=[...])`.
  Parse a strict structured response (faithfulness PASS/FAIL + reason, safety PASS/FAIL + reason);
  PASS only when both pass.
- **Execution note:** Test-first — the fail-closed matrix is the contract; pin it before wiring the
  real `urllib` caller.
- **Patterns to follow:** `pipeline/evals/setup_langfuse_evaluators.py` (`urllib` request helper,
  Bearer auth, fail-closed returns, stdlib-only); the Cloudflare-1010 User-Agent note.
- **Test scenarios:**
  - Stub returns both dimensions PASS → `Verdict.pass is True`, no reasons.
  - Stub returns faithfulness FAIL → pass False, reason names the spec gap.
  - Stub returns safety FAIL (leaked secret/PII/revenue) → pass False, safety reason present.
  - Empty diff → pass False ("missing diff"), no HTTP call made.
  - Empty/missing spec → pass False ("missing spec"), no HTTP call made.
  - `http_caller` raises / returns non-2xx → pass False ("…error…"), never True.
  - Unparseable/garbage LLM body → pass False ("unparseable"), never True.
  - Oversized diff → truncated with marker before the call; still scored.
  - `judge` is pure with an injected caller: no real network in tests.
- **Verification:** `pytest pipeline/tests/test_impl_judge.py` green; every non-PASS branch yields
  `pass=False` (prove the fail-closed contract by asserting no path defaults to True).

### U2. CLI entrypoint + exit-code mapping

- **Goal:** A `main()` that reads the diff/spec/issue, runs `judge`, prints the verdict, and exits
  `0` (PASS) / `1` (FAIL-or-error) — the surface the wgmesh check will invoke.
- **Requirements:** KTD1, KTD5.
- **Dependencies:** U1.
- **Files:**
  - `pipeline/evals/impl_judge.py` (the `main()` + argparse)
  - `pipeline/tests/test_impl_judge.py`
- **Approach:** argparse: `--diff-file`, `--spec-file`, `--issue` (optional). Read files
  (missing/unreadable → fail-closed FAIL, exit 1). Require `OPENROUTER_API_KEY` (absent → exit 2,
  distinct config error, like `setup_langfuse_evaluators.py`'s missing-env handling). Print a
  compact report (verdict + per-dimension reasons). Map: PASS→0, FAIL→1, config/usage error→2.
- **Test scenarios:**
  - `main(["--diff-file", d, "--spec-file", s])` with a stubbed PASS judge → prints PASS, returns 0.
  - Stubbed FAIL → prints FAIL + reasons, returns 1.
  - Missing `--diff-file` path on disk → fail-closed, returns 1 (not 0).
  - `OPENROUTER_API_KEY` unset (non-stub path) → returns 2 with a clear message, no call.
  - The judge is injectable in `main` so the CLI test needs no network.
- **Verification:** the three exit codes (0/1/2) are produced deterministically by the matrix above;
  no path exits 0 without an explicit PASS.

---

## Risks & Dependencies

- **R1 — Fail-open is the cardinal sin.** A judge that passes on error would let bad code
  auto-merge once wired. Mitigation: KTD1 + tests assert every error/ambiguity branch is
  `pass=False`/exit 1; "prove the test bites" by checking no default-True path exists.
- **R2 — DeepSeek/OpenRouter response shape drift.** Strict parsing could reject a valid-but-
  differently-shaped response. Mitigation: request a constrained format; on parse failure, FAIL
  (blocks merge, never wrong-merges) — acceptable and surfaced.
- **R3 — Rubric drift from the evaluators.** Lifting rubric text risks divergence from
  `setup_langfuse_evaluators.py`. Mitigation: import/reference the rubric source where practical;
  if copied, note the source so a future change updates both.
- **Dependency:** `OPENROUTER_API_KEY` (DeepSeek) at runtime; none for tests (injected caller). No
  new pip deps (stdlib `urllib`).

## Verification (end-to-end)

1. `pytest pipeline/tests/test_impl_judge.py -q` green — full fail-closed matrix.
2. Manual smoke (optional, with a real key): run the CLI against a known-good diff/spec → PASS exit
   0; against a spec-ignoring diff → FAIL exit 1.
3. Hand-off: the wgmesh `impl-judge.yml` check (origin plan U2) invokes
   `python -m wgmesh_pipeline...` / this module to gate auto-merge.
