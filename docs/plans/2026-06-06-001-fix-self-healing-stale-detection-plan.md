---
title: "fix: Self-Healing stale-detection query is malformed — heals nothing across 777 runs"
status: active
date: 2026-06-06
type: fix
depth: standard
origin: pulse/KPI analysis (3-day SLA breach), conversation 2026-06-06
---

# fix: Self-Healing stale-detection query is malformed — heals nothing across 777 runs

## Summary

`.github/workflows/pipeline-health.yml` (the Self-Healing loop) detects zero stale
work items on every run because its three stale-detection queries pass jq's `--arg`
flag to `gh issue list --jq`, which does not accept it. `gh` errors on the malformed
invocation, the trailing `|| true` swallows the error, the output file is empty, the
per-phase counter stays `0`, and no healing action fires. The state file confirms the
symptom: `checks_run: 777`, `issues_healed_total: 0`, `retry_tracker: {}` (empty —
not one retry ever attempted).

Fix the three queries to embed the cutoff timestamp directly into the jq filter
string, remove the error-masking on the detection step so a future malformed query
fails loud, and harden the existing e2e test so it asserts the detector actually
finds and acts on a stale item (the regression guard that was missing).

---

## Problem Frame

**Symptom (observed):** Self-Healing is a no-op. `company/pipeline-health-state.json`
shows 777 checks run, 0 issues healed, empty retry tracker — a flat trend for days.
Stuck items in the target seed repo never get their stalled stage re-triggered.

**Root cause (verified locally):** In `pipeline-health.yml`, the stale sweeps call:

```
gh issue list --repo "$TARGET_REPO" --state open \
  --label "needs-triage" --limit 50 \
  --json number,title,createdAt,labels \
  --jq --arg cutoff "$cutoff" \
  '.[] | select(.createdAt < $cutoff) | @json' \
  > /tmp/stale_triage.json || true
```

`gh`'s `--jq` (`-q`) flag takes exactly **one** argument: the filter string. It has
no `--arg` passthrough. So `gh` reads `--arg` as the filter value, then treats
`cutoff`, `$cutoff` (already shell-expanded), and the real filter as unknown
positional arguments. Reproduced locally:

```
$ gh issue list --repo ... --json number --jq --arg c "z" '.[]'
unknown arguments ["c" "z" ".[]"]; please quote all values that have spaces
```

`gh` exits non-zero, `|| true` masks it, `/tmp/stale_triage.json` is empty, the
`while read` loop body never executes, `local_stale` stays `0`, and
`STALE_TRIAGE_FOUND` is `0`. The same malformed pattern repeats in all three
detection phases.

**Scope note — wgmesh vs template.** `TARGET_REPO` is
`atvirokodosprendimai/wgmesh` (the Seed product). The 22 stuck items surfaced in the
pulse analysis live in `ai-pipeline-template` (the pipeline's own meta-backlog) and
are **out of scope** here — Self-Healing is correctly pointed at the Seed, not the
template. This plan restores healing of the Seed repo. Whether the template's own
meta-backlog should be swept is a separate decision (see Scope Boundaries).

---

## Requirements

- **R1.** The three stale-detection sweeps (`needs-triage`, `copilot-triaging`,
  `approved-for-build`) must produce a correct list of items older than their cutoff,
  using a well-formed `gh issue list --jq` invocation.
- **R2.** A malformed or failing detection query must NOT be silently swallowed — the
  step must surface the failure (Andon: stop the line on a broken detector) rather
  than reporting "0 stale" indistinguishably from "query crashed".
- **R3.** The existing e2e test must assert that the detector finds and acts on a
  seeded stale item, so this class of regression cannot reach `main` green again.
- **R4.** No behavior change to the healing actions themselves (label toggle,
  retry/cooldown tracking, escalation, circuit breaker) — only the detection input
  and its error handling.

---

## Key Technical Decisions

**KTD1 — Embed cutoff into the jq string, drop `--arg`.** Replace
`--jq --arg cutoff "$cutoff" '.[] | select(.createdAt < $cutoff) | @json'` with a
single interpolated filter:
`--jq ".[] | select(.createdAt < \"$cutoff\") | @json"`. The cutoff is an
ISO-8601 timestamp with no embedded quotes or shell metacharacters (it comes from
`date -u`), so direct interpolation is safe. Rationale: `gh --jq` has no `--arg`; this
is the minimal correct form and matches the other well-formed `--jq` calls already in
the file (e.g., the `cross-referenced` event query).

**KTD2 — Fail loud on detection-query error, keep loop-body resilience.** Remove the
`|| true` that masks the `gh issue list` exit code on the detection call. Instead,
capture the exit status and, on non-zero, emit `::error::` and mark the run failed
(reuse the existing `Assert state mutation` / `Fail if state mutation assertion
failed` failure path, or set an error flag the circuit-breaker/assert step already
reads). The `|| true` on individual *healing actions* inside the loop (label edits,
issue creates) stays — one item failing to heal should not abort the sweep. Only the
*detector* must be fail-loud. Rationale: memory — "cron success ≠ state mutation";
777 green runs hid a totally broken detector.

**KTD3 — e2e test asserts detection, not just dispatch.** The current test seeds
issues and dispatches the workflow with `cutoff_override_minutes=1`, but its
assertions do not fail when the detector finds nothing. Strengthen it to read the
audit log (or the resulting label toggle / `retry_tracker` entry) and assert the
seeded stale item produced a `retrigger_triage` action. Rationale: memory —
"untested glue steps are unverified"; a live e2e that never asserts the heal happened
is theater.

---

## High-Level Technical Design

Current (broken) vs fixed detection data flow:

```
BROKEN:
  gh issue list --jq --arg cutoff $cutoff '<filter>'
      └─► gh: "unknown arguments" → exit 1
          └─► || true  → exit 0, /tmp/stale_*.json EMPTY
              └─► while read: 0 iterations
                  └─► local_stale=0 → STALE_*_FOUND=0 → no heal → healed_total stays 0

FIXED:
  gh issue list --jq ".[] | select(.createdAt < \"$cutoff\") | @json"
      └─► valid filter → JSON lines of stale items
          └─► while read: N iterations
              └─► label toggle re-triggers stalled stage, retry_tracker updated
                  └─► STALE_*_FOUND=N → healed_total increments
      └─► (on gh failure) ::error:: + run marked failed  ← KTD2 fail-loud
```

---

## Implementation Units

### U1. Fix the three malformed stale-detection queries

- **Goal:** Make all three stale sweeps return correct results.
- **Requirements:** R1, R4
- **Dependencies:** none
- **Files:** `.github/workflows/pipeline-health.yml`
- **Approach:** In the three steps `Check stale needs-triage issues`,
  `Check stale copilot-triaging issues`, and `Check stale approved-for-build PRs`,
  replace the `--jq --arg cutoff "$cutoff" '<filter>'` form with a single
  interpolated `--jq` string per KTD1. Verify each sweep's output file
  (`/tmp/stale_triage.json`, `/tmp/stale_copilot.json`, the approved-build equivalent)
  is consumed by its `while read` loop unchanged. Confirm the `@json` line-per-item
  shape the loops expect is preserved.
- **Patterns to follow:** the already-correct `--jq '.[] | @json'` and
  `--jq '[.[] | select(.event == "cross-referenced" ...)] | length'` calls in the
  same file.
- **Test scenarios:**
  - Covers R1. Given an open issue labeled `needs-triage` with `createdAt` older than
    the cutoff, the fixed filter emits exactly that issue as a `@json` line.
  - Given an issue newer than the cutoff, the filter emits nothing.
  - Given a cutoff string, the rendered `gh ... --jq` command parses without
    "unknown arguments" (the local reproduction now succeeds).
  - All three phases produce non-empty output when a matching stale item exists.
- **Verification:** A dry `gh issue list ... --jq "<interpolated>"` run against the
  target repo returns JSON lines (or empty) with no `unknown arguments` error.

### U2. Make the detection query fail loud instead of masking errors

- **Goal:** A broken/failing detector fails the run rather than reporting 0 silently.
- **Requirements:** R2
- **Dependencies:** U1
- **Files:** `.github/workflows/pipeline-health.yml`
- **Approach:** Remove `|| true` from the three `gh issue list ... > /tmp/stale_*.json`
  detection calls. Capture exit status; on non-zero emit `::error::detection query
  failed for <phase>` and propagate to the existing run-failure mechanism (the
  `Fail if state mutation assertion failed` gate or an equivalent error flag the
  final step honors). Leave the in-loop `|| true` on healing actions intact per KTD2.
  Ensure an empty-but-successful query (genuinely zero stale items) still exits 0 and
  is distinguished from a query error.
- **Patterns to follow:** existing `Assert state mutation` and
  `Fail if state mutation assertion failed` steps in the same workflow.
- **Test scenarios:**
  - Covers R2. Detector exits 0 with zero stale items → run succeeds, no error
    annotation.
  - Detector exits non-zero (simulate malformed filter) → run is marked failed and an
    `::error::` is emitted.
  - A healing action failing inside the loop (one label edit errors) does NOT abort
    the sweep or fail the run (resilience preserved).
- **Verification:** Re-introducing the old `--arg` form makes the workflow run fail
  (red), proving the detector is no longer silently masked.

### U3. Strengthen the e2e test to assert the heal occurred

- **Goal:** Guard against silent-detector regressions reaching `main`.
- **Requirements:** R3
- **Dependencies:** U1, U2
- **Files:** `company/scripts/test-self-healing-e2e.sh`
- **Approach:** After dispatching `pipeline-health.yml` with
  `cutoff_override_minutes=1` against a seeded stale `needs-triage` issue, assert the
  run produced a healing effect: either an audit-log entry with
  `action: "retrigger_triage"` for the seeded issue number, or an observed
  remove-then-add label toggle, or a `retry_tracker` entry for that number in the
  committed state. Fail the test (non-zero exit) when no heal is detected, with a
  clear message. Keep the existing seeding/cleanup logic.
- **Execution note:** characterization-first — first make the test assert against the
  CURRENT (broken) workflow and confirm it FAILS, then confirm it passes after U1/U2.
- **Test scenarios:**
  - Covers R3. Seeded stale `needs-triage` issue → after dispatch, audit log /
    state shows a `retrigger_triage` action for that issue → test passes.
  - Detector broken (old `--arg` form) → no heal action recorded → test fails loud.
  - No stale items seeded → test does not false-positive (asserts only on the seeded
    number).
- **Verification:** Running the test against `HEAD~` (pre-fix) exits non-zero;
  against the fixed workflow exits zero.

---

## Scope Boundaries

**In scope:** the three malformed detection queries, their error masking, and the
e2e regression guard in `pipeline-health.yml` + `test-self-healing-e2e.sh`.

**Out of scope / non-goals:**
- Changing healing actions, retry/cooldown logic, circuit breaker, or escalation
  behavior (R4 — they are correct; they just never receive input).
- The `--search "spec: Issue #N"` / `--search "impl: Issue #N"` dedup lookups
  (lines ~282, ~422). They are a separate known fragility (memory: gh Search API
  eventual-consistency floods); not touched here unless U1 testing shows they also
  block the loop.

### Deferred to Follow-Up Work
- **Template meta-backlog sweep.** The 22 stuck items in `ai-pipeline-template`
  itself are not covered by a Seed-targeted heal. Decide separately whether a
  second `TARGET_REPO` (or a matrix) should sweep the template's own pipeline, or
  whether those items should be triaged/closed by the Observation Loop against the
  end goal (1 paying cloudroof customer).
- **Detector contract test in CI** (not live e2e): a fast unit-level assertion that
  the rendered `gh --jq` string parses, runnable on every PR without dispatching the
  workflow.

---

## Risks & Dependencies

- **Risk:** Interpolating `$cutoff` into the jq string is safe only because the value
  is a clean ISO timestamp. Mitigation: cutoff is always produced by `date -u`;
  U1 tests assert the rendered command parses. Do not generalize this interpolation
  to user-controlled strings.
- **Risk:** Removing `|| true` (U2) could make transient `gh`/network blips fail the
  run. Mitigation: distinguish query-error (fail) from empty-result (succeed); only a
  non-zero `gh` exit fails the run, and the 30-min cron retries naturally.
- **Dependency:** Requires the GitHub App token already configured in the workflow
  (`APP_ID` / `APP_PRIVATE_KEY`) — unchanged.

---

## Verification Strategy

1. Local: reproduce the `unknown arguments` error pre-fix; confirm the interpolated
   form parses post-fix (done during planning for the needs-triage phase).
2. e2e: `company/scripts/test-self-healing-e2e.sh` red on pre-fix workflow, green on
   fixed workflow (U3).
3. Production signal: after merge, within a few 30-min cycles
   `company/pipeline-health-state.json` shows `issues_healed_total > 0` and/or
   `retry_tracker` gains entries — the first non-zero heal in 777 runs is the
   acceptance signal.
