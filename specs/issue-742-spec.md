# Specification: Issue #742

## Classification
feature

## Deliverables
code

## Problem Analysis

The `active_stuck_issues` metric in `STRATEGY.md` and the corresponding computation in the "Compute self-heal rate and active stuck issues" step of `.github/workflows/strategy-audit.yml` only count two stuck states: open `needs-human` issues and issues in retry cooldown >24h. This means issues stuck in three new post-verification states are invisible to the pulse metric:

- `awaiting-verification` — implementation merged but the verifier workflow (introduced by wgmesh#568) has not concluded within 6h.
- `e2e-stalled` — verifier triggered but timed out (e.g. infrastructure provisioning failure).
- `e2e-failed` — verifier ran and reported a red result requiring a real fix.

Additionally, the existing definition omits the `copilot-triaging >24h` bucket, which the proposal adds to make the list complete.

The pulse report (strategy-audit drift PR body, rendered via the "Detect drift, build audit body, manage PR" step) shows `active_stuck_issues` as a single number with no per-bucket breakdown, so the founder cannot tell which state issues are stuck in.

The three new labels (`awaiting-verification`, `e2e-stalled`, `e2e-failed`) are not defined in `.github/labels.yml`, so they would not appear in `gh issue list` results even if they were queried.

## Implementation Tasks

### Task 1: Update STRATEGY.md `active_stuck_issues` definition

- **File:** `STRATEGY.md` (modify)
- **Where:** In the `## Key metrics` section, at the bullet starting `**Active stuck issues**`
- **What:** Replace the definition with the extended source list
- **Detail:** Change the text from `open issues at \`needs-human\` or in retry cooldown >24h` to `open issues matching: \`needs-human\`, OR \`copilot-triaging\` >24h, OR \`awaiting-verification\` >6h, OR \`e2e-stalled\`, OR \`e2e-failed\`, OR in retry cooldown >24h`. Keep `Source: \`gh issue list\`` and `Leading.` unchanged.

### Task 2: Add new labels to `.github/labels.yml`

- **File:** `.github/labels.yml` (modify)
- **Where:** After the `health-check` label at the end of the file, append three new labels under a new `# === Verification Labels ===` comment
- **What:** Add `awaiting-verification` (color `BFD4F2`, description `"Impl merged; automated verifier has not concluded"`), `e2e-stalled` (color `F9D0C4`, description `"E2E verifier triggered but timed out or stalled"`), and `e2e-failed` (color `B60205`, description `"E2E verifier ran and reported failure; fix required"`)
- **Detail:** Colors follow existing conventions — informational states use blue-family (`BFD4F2`), warning states use orange-family (`F9D0C4`), and failure states use the same red (`B60205`) as `needs-human`. Label names must match exactly the labels that the wgmesh verifier workflow (wgmesh#568) applies; verify against the verifier workflow before merge.

### Task 3: Extend `active_stuck_issues` computation in `strategy-audit.yml`

- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** Inside the "Compute self-heal rate and active stuck issues" step, after the `needs_human_count` line that runs `gh issue list --label needs-human`
- **What:** Add four additional `gh issue list` queries and export per-bucket counts as `GITHUB_ENV` variables; replace the single `active_stuck_issues` arithmetic with a sum of all buckets.
- **Detail:** Implement as follows. After the existing `needs_human_count` line, add:
  1. `copilot_triaging_stale_count` — list open issues with label `copilot-triaging`, filter with `--jq` to keep only those where `createdAt` is more than 24h before `$now` (use the same `$now` variable already defined in the step); count with `jq 'length'`.
  2. `awaiting_verification_stale_count` — list open issues with label `awaiting-verification`, filter to keep only those where `createdAt` is more than 6h before `$now`; count with `jq 'length'`.
  3. `e2e_stalled_count` — list all open issues with label `e2e-stalled`; count with `jq 'length'`.
  4. `e2e_failed_count` — list all open issues with label `e2e-failed`; count with `jq 'length'`.
  Replace `active_stuck_issues=$((needs_human_count + cooldown_count))` with a sum of all six buckets. Export each bucket count individually: `STUCK_NEEDS_HUMAN`, `STUCK_COPILOT_TRIAGING`, `STUCK_AWAITING_VERIFICATION`, `STUCK_E2E_STALLED`, `STUCK_E2E_FAILED`, `STUCK_COOLDOWN` to `$GITHUB_ENV`, in addition to the existing `ACTIVE_STUCK_ISSUES` total. Keep `SELF_HEAL_RATE` and `ACTIVE_STUCK_ISSUES` variable names unchanged so downstream steps (PostHog emit, baseline JSON, `metric_row` call) continue to work without modification.

### Task 4: Render per-bucket stuck-issue breakdown in the audit PR body

- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** In the "Detect drift, build audit body, manage PR" step, inside the heredoc block that writes `/tmp/audit-body.md`, after the `## Metric drift` table and before `## Milestone status`
- **What:** Add a `## Stuck issues by bucket` section that renders a markdown table with one row per stuck bucket and its current count.
- **Detail:** The section must appear only when `ACTIVE_STUCK_ISSUES` is non-zero OR always (prefer always for observability). Use shell variable expansion to read the six `STUCK_*` env vars. Render a table:
  ```
  ## Stuck issues by bucket
  | Bucket | Count | SLA |
  |---|---:|---|
  | needs-human | N | no SLA (human required) |
  | copilot-triaging >24h | N | 24h |
  | awaiting-verification >6h | N | 6h |
  | e2e-stalled | N | immediate |
  | e2e-failed | N | immediate |
  | retry-cooldown >24h | N | 24h |
  ```
  Values come from `$STUCK_NEEDS_HUMAN`, `$STUCK_COPILOT_TRIAGING`, `$STUCK_AWAITING_VERIFICATION`, `$STUCK_E2E_STALLED`, `$STUCK_E2E_FAILED`, `$STUCK_COOLDOWN`. Also update the `active_stuck_issues` drift suggestion message (the `active_stuck_issues` case in the drift suggestions `while` loop) to reference the bucket table instead of the generic `needs-human` text.

### Task 5: Update `.compound-engineering/config.local.example.yaml` with `pulse_metric_sources`

- **File:** `.compound-engineering/config.local.example.yaml` (modify)
- **Where:** At the end of the file, after the `work_delegate_effort` comment block
- **What:** Add a new commented `# --- Pulse metric sources ---` section documenting the `pulse_metric_sources.active_stuck_issues` configuration knob
- **Detail:** Add the following commented YAML block (all lines commented out, serving as documentation):
  ```yaml
  # --- Pulse metric sources (active_stuck_issues) ---
  # pulse_metric_sources:
  #   active_stuck_issues:
  #     - label: needs-human
  #     - label: copilot-triaging
  #       age_hours: 24
  #     - label: awaiting-verification
  #       age_hours: 6
  #     - label: e2e-stalled
  #     - label: e2e-failed
  #     - source: cooldown
  #       age_hours: 24
  ```
  This is documentation only; the values are hard-coded in `strategy-audit.yml`. The section exists so operators know which labels and thresholds drive the metric and can customize if they fork the template.

### Task 6: Confirm verifier label emission (cross-repo validation step)

- **File:** None — this is a verification step, not a code change
- **Where:** N/A
- **What:** Before merging the implementation PR, verify that the verifier workflow introduced in wgmesh#568 applies the labels `awaiting-verification`, `e2e-stalled`, and `e2e-failed` with exactly those names on the wgmesh repo's issues. If the labels differ, update Task 2 and Task 3 to match the actual label names.
- **Detail:** Run `gh label list --repo atvirokodosprendimai/wgmesh | grep -E "awaiting-verification|e2e-stalled|e2e-failed"` and compare against the names added in Task 2. Any mismatch is a blocking inconsistency.

## Affected Files

`STRATEGY.md`                                                (modify)
`.github/labels.yml`                                         (modify)
`.github/workflows/strategy-audit.yml`                       (modify)
`.compound-engineering/config.local.example.yaml`            (modify)

## Test Strategy

- `gh act -j audit --dry-run` (if act is available) or `workflow_dispatch` on a fork passes with new env vars `STUCK_NEEDS_HUMAN`, `STUCK_COPILOT_TRIAGING`, `STUCK_AWAITING_VERIFICATION`, `STUCK_E2E_STALLED`, `STUCK_E2E_FAILED`, `STUCK_COOLDOWN` exported and non-empty in the job log.
- Manually label a test issue in `atvirokodosprendimai/wgmesh` with `awaiting-verification` and set `createdAt` >6h ago (or use a pre-existing issue); trigger `strategy-audit` via `workflow_dispatch`; confirm `STUCK_AWAITING_VERIFICATION` is ≥1 and `ACTIVE_STUCK_ISSUES` is ≥1 in the workflow log.
- Confirm the generated audit PR body (from `/tmp/audit-body.md`) contains the `## Stuck issues by bucket` table with all six rows.
- Confirm `STRATEGY.md` bullet for `active_stuck_issues` now lists all five label sources plus cooldown.
- Confirm `.github/labels.yml` defines `awaiting-verification`, `e2e-stalled`, `e2e-failed` and that `sync-labels.yml` workflow run applies them to `atvirokodosprendimai/wgmesh` without error.
- Sanity check: open a real `e2e-failed` issue in wgmesh, run `strategy-audit` — pulse `active_stuck_issues` must be ≥1. This answers the post-mortem question: *could this metric show all-green while the founder bleeds revenue?* — the answer must be no.

## Estimated Complexity

medium (3 files, ~60 lines of shell and YAML across changes)
