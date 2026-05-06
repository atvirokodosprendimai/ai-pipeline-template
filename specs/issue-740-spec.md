# Specification: Issue #740

## Classification
fix

## Deliverables
both

## Problem Analysis

`STRATEGY.md` defines a single metric — **Goose autonomous-ship rate** — as the fraction of bot-authored PRs that merged with zero human intervention (no non-bot comments, no non-bot review body, no `needs-human` label). This definition treats "code merged cleanly" as equivalent to "bug actually fixed."

The failure mode: PR #564 merged with 100 % clean-ship signal while its linked issue remained in `awaiting-verification`. Pulse showed 1/1 = 100 % autonomous-ship while the fix had not been confirmed to work under real conditions. This is the same pattern that prompted the L2+L3 gate (wgmesh#559).

Concretely, the gap is in `strategy-audit.yml`, inside the step **"Compute lead time + autonomous-ship rate"**:

- `bot_clean` is incremented when a merged PR has no non-bot comments, no non-bot review body, and no `needs-human` label.
- There is no check that the linked issue was subsequently closed with a `verified` label (as opposed to auto-closed by keyword or manually closed by a human).

The `verified` label does not yet exist in `.github/labels.yml`. The `docs/pulse-reports/2026-05-04_20-46.md` template shows `autonomous_merge_clean` as a single value rather than a ship/close pair.

## Implementation Tasks

### Task 1: Add `verified` label
- **File:** `.github/labels.yml` (modify)
- **Where:** After the `needs-human` label entry at the end of the file
- **What:** Add a new label entry `verified` with a green colour and description "Fix confirmed working in production or staging by a human or automated test"
- **Detail:** Use colour `0E8A16` (matches `approved-for-build` and `spec-ready` — the "green means done" convention already in the file). The label must exist so that workflows and the close-rate metric can query it without failing on missing-label errors.

### Task 2: Update `STRATEGY.md` Key Metrics section
- **File:** `STRATEGY.md` (modify)
- **Where:** Replace the single bullet for `Goose autonomous-ship rate` inside the `## Key metrics` section
- **What:** Split the single metric into two adjacent bullets:
  1. `autonomous_ship_rate` — % of bot-authored impl PRs merged with no escalation (no non-bot review/comment, no `needs-human` label). Source: seed-repo PR data. Leading.
  2. `autonomous_close_rate` — % of bot-authored impl PRs merged **and** whose linked issue was subsequently closed via the `verified` label (not via auto-close keyword, not via manual close without the label). Source: seed-repo issue labels. Leading.
- **Detail:** Preserve the existing frontmatter (`name`, `last_updated`). The two new bullets replace the old single `Goose autonomous-ship rate` bullet verbatim. No other section of `STRATEGY.md` changes in this task.

### Task 3: Compute `autonomous_close_rate` in `strategy-audit.yml`
- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** Inside the step named **"Compute lead time + autonomous-ship rate"**, after the block that increments `bot_clean`
- **What:** Add computation of `autonomous_close_rate` using the following algorithm and emit `AUTONOMOUS_CLOSE_RATE` to `$GITHUB_ENV`.
- **Detail:**
  - Introduce two counters `close_eligible=0` and `close_verified=0` initialised before the PR loop alongside `bot_total` and `bot_clean`.
  - Inside the loop, for every PR counted in `bot_total` (bot-authored merged PR), increment `close_eligible`.
  - For each such PR, iterate `closingIssuesReferences` (already fetched into `/tmp/pr.json`). For each linked issue number, call `gh issue view <number> --repo "$TARGET_REPO" --json labels --jq '[.labels[].name] | any(. == "verified")'`. If any linked issue returns `true`, increment `close_verified` and break the inner loop (one verified issue is sufficient to count the PR).
  - After the PR loop, compute `autonomous_close_rate=$(jq -n --argjson clean "$close_verified" --argjson total "$close_eligible" 'if $total == 0 then null else (($clean / $total) * 10000 | round) / 10000 end')`.
  - Append `echo "AUTONOMOUS_CLOSE_RATE=$autonomous_close_rate" >> "$GITHUB_ENV"`.
  - **No change** to how `AUTONOMOUS_SHIP_RATE` is computed — ship-rate definition is unchanged.

### Task 4: Persist `autonomous_close_rate` in baseline JSON and drift detection
- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** Inside the step named **"Detect drift, build audit body, manage PR"**
- **What:** Wire `AUTONOMOUS_CLOSE_RATE` into metric rows, baseline JSON, and the suggested-edits block.
- **Detail:**
  - Add a `metric_row` call for `autonomous_close_rate "Autonomous-close rate" drop` immediately after the existing `autonomous_ship_rate` `metric_row` call.
  - Update the `current_metrics` `jq -nc` invocation: add `--argjson close "$AUTONOMOUS_CLOSE_RATE"` and include `autonomous_close_rate:$close` in the JSON object.
  - In the suggested-edits `case` block, add a case for `autonomous_close_rate`: "Autonomous-close rate dropped ${pct}% (baseline ${baseline} → current ${current}). Impl PRs are merging but linked issues are not being verified; check the verification workflow in wgmesh."
  - The drift direction for `autonomous_close_rate` is `drop` (same as `autonomous_ship_rate`).

### Task 5: Render both metrics in pulse report template comment
- **File:** `docs/pulse-reports/2026-05-04_20-46.md` (modify)
- **Where:** In the `## Usage` metrics table, after the `autonomous_merge_clean` row
- **What:** Add a second row `autonomous_close_rate` so human readers see the ship/close pair side by side.
- **Detail:** The new row format follows the existing table structure: `| \`autonomous_close_rate\` (value) | 0/1 (ship-rate=1/1 close-rate=0/1 demo) | seed-repo-issues + verified label |`. This is a one-time backfill of the single existing pulse report. Future pulse reports will naturally include both rows once the workflow emits both values. Note: this pulse report file is historical; the edit is documentation only and does not affect workflow execution.

### Task 6: Update `.compound-engineering/config.local.example.yaml` with pulse_metric_sources comment
- **File:** `.compound-engineering/config.local.example.yaml` (modify)
- **Where:** At the end of the file
- **What:** Add a commented-out `pulse_metric_sources` block that documents both metric keys.
- **Detail:** Add the following block:

  ```yaml
  # --- Pulse metric sources ---
  # pulse_metric_sources:
  #   autonomous_ship_rate: seed-repo-pr-data   # PRs merged with no escalation_posted
  #   autonomous_close_rate: seed-repo-issues   # PRs merged AND linked issue closed via verified label (NOT auto-close keyword bypass, NOT manual close)
  ```

  This documents the expected keys so that future config.local.yaml consumers know both metric names and their data sources.

### Task 7: Backfill — document the delta in the existing pulse report
- **File:** `docs/pulse-reports/2026-05-04_20-46.md` (modify)
- **Where:** In the `## Followups` section, after the existing item about aggregate autonomous-ship rate
- **What:** Add a followup item that documents the backfill delta: for the 2026-05-04 window, `autonomous_ship_rate` is unchanged from the original computation, while `autonomous_close_rate` would be lower (or 0) because linked issues had not received the `verified` label at merge time.
- **Detail:** The note must not reference any issue-comment text for the close signal (per acceptance criteria). It should state: "**Backfill note (Issue #740):** `autonomous_ship_rate` for this window remains as computed (3/13 clean bot PRs). `autonomous_close_rate` for this window is 0/13 — zero linked issues carried the `verified` label at merge time. Ship-rate ≠ close-rate; see Issue #740 for metric definition change."

## Affected Files

`.github/labels.yml`                                  (modify)
`STRATEGY.md`                                          (modify)
`.github/workflows/strategy-audit.yml`                 (modify)
`.compound-engineering/config.local.example.yaml`      (modify)
`docs/pulse-reports/2026-05-04_20-46.md`               (modify)

## Test Strategy

- `act -j audit --dryrun` (or workflow_dispatch after merge) validates the `strategy-audit.yml` step parses without bash errors.
- Sanity test (manual): create a test window with 1 bot-authored impl PR merged (no escalation) whose linked issue has no `verified` label → `autonomous_ship_rate=1/1`, `autonomous_close_rate=0/1`. Add the `verified` label to the issue → re-run audit → `autonomous_close_rate=1/1`.
- `grep -c 'autonomous_close_rate' .github/workflows/strategy-audit.yml` returns ≥ 4 (metric_row call + current_metrics jq + drift case + GITHUB_ENV emit).
- `grep 'verified' .github/labels.yml` returns the new label entry.
- `grep 'autonomous_close_rate' STRATEGY.md` returns the new bullet.
- `grep 'autonomous_close_rate' docs/pulse-reports/2026-05-04_20-46.md` returns the backfill row.
- No metric reads from issue-comment text — `gh issue view ... --json labels` reads labels only.

## Estimated Complexity

medium (3–5 files, ~80 lines changed across workflow, strategy doc, labels, config example, and pulse report)
