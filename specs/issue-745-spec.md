# Specification: Issue #745

## Classification
feature

## Deliverables
code

## Problem Analysis

The `strategy-audit.yml` workflow collects five key metrics and emits a daily report, but it performs no cross-check between individually "green" metric values and other evidence already available in the same data collection run. The concrete instance from 2026-05-06 shows `autonomous_ship_rate: 1/1 (100%)` while `active_stuck_issues: 2` and the sole "shipped" PR was sitting in `awaiting-verification`. These facts co-exist in the same run's data; the contradiction is detectable but not detected.

The current "Detect drift, build audit body, manage PR" step in `strategy-audit.yml` only checks drift vs the previous baseline. It never asks: *does this green metric contradict something else visible in the same data snapshot?*

The `company/strategy-audit-baseline.json` persists per-run metrics but has no place for contradiction findings. The `.compound-engineering/config.local.example.yaml` is the declared home for local config (audit rules); it currently covers only work-delegation settings.

There is no `## Contradictions` section in the generated audit PR body (`/tmp/audit-body.md`), and no `(unaudited)` marker applied to metric table rows when the contradiction check cannot confirm cleanliness.

## Implementation Tasks

### Task 1: Add audit-rule schema to config example

- **File:** `.compound-engineering/config.local.example.yaml` (modify)
- **Where:** After the last existing comment block (end of file)
- **What:** Add a new `pulse_audit_rules:` top-level key with five initial rule entries — one per metric in the issue table. Each rule has the fields: `metric` (string key matching `strategy-audit-baseline.json`), `green_condition` (human-readable), `failure_modes` (list of strings), and `evidence_query` (structured object with `type`, and query-specific sub-fields).
- **Detail:** The five initial entries with their `evidence_query` descriptions:
  - `autonomous_ship_rate`: queries open PRs in `TARGET_REPO` with the `awaiting-verification` label and a staleness threshold of 24h.
  - `autonomous_close_rate`: queries issues closed in the last 30 days without a `verified` label.
  - `active_stuck_issues`: queries open issues with no `type:*` label.
  - `paid_customers`: checks whether `fetch_status.paid_customers == "ok"` (i.e., the value came from a structured source, not null).
  - `spec_coverage`: queries open spec PRs older than 24h that have not merged.
  Include comments explaining each field so the file remains a self-documenting example.

### Task 2: Implement self-audit step in strategy-audit workflow

- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** After the existing `Fetch paid customers from chimney` step and before the `Detect drift, build audit body, manage PR` step
- **What:** Add a new step named `Run self-audit contradiction checks` that reads the five hardcoded audit rules, executes each `evidence_query` via the `gh` CLI, and emits two env vars: `AUDIT_CONTRADICTIONS` (a JSON array of contradiction objects) and `AUDIT_UNAUDITED_METRICS` (a JSON array of metric key strings whose green state could not be confirmed clean).
- **Detail:** Each contradiction object has the shape `{metric, green_value, failure_mode, evidence, remedy}` where `remedy` is a founder-readable sentence explaining what would need to change for the metric to be trustworthy. The step runs only when `steps.skip-guard.outputs.skip != 'true'`. Use `GH_TOKEN: ${{ secrets.PUSH_TOKEN }}` and `TARGET_REPO: ${{ inputs.target_repo || 'atvirokodosprendimai/wgmesh' }}`. Rules to implement:
  - **`autonomous_ship_rate`**: skip if value is `null`; if value >= threshold (e.g., any positive rate) then query `gh pr list --repo "$TARGET_REPO" --state open --label awaiting-verification --json number,createdAt` — any PR older than 24h is a contradiction. Emit one entry per stale PR with `remedy: "Close or re-verify PR #N before counting its source spec as shipped."`.
  - **`autonomous_close_rate`**: query issues closed in the last 30 days in `TARGET_REPO` that lack a `verified` label; each is a potential keyword-bypass close. If any found, emit a contradiction with `failure_mode: "closed via auto-keyword bypass"` and `remedy: "Add 'verified' label or reopen issue #N to confirm closure was intentional."`.
  - **`active_stuck_issues=0`**: if current `ACTIVE_STUCK_ISSUES == 0`, query open issues with no label matching `type:*`; if any found, emit contradiction with `failure_mode: "untriaged issues invisible to stuck-count"` and `remedy: "Triage issue #N with a type:* label so the stuck-count sees it."`.
  - **`paid_customers`**: if `PAID_CUSTOMERS` is not `null` and `PAID_FETCH_STATUS != "ok"`, emit contradiction with `failure_mode: "count sourced from aspirational text, not structured data"` and `remedy: "Fix chimney HTML selector or integrate a structured Polar/Stripe webhook so paid_customers reflects a machine-verifiable count."`.
  - **`spec_coverage`**: query open PRs in `GITHUB_REPOSITORY` with title matching `^spec:` that were created more than 24h ago and have not been merged; each is a contradiction with `failure_mode: "spec PR opened but never merged"` and `remedy: "Review spec PR #N — merge, close, or re-assign it so spec_coverage reflects deliverable specs, not open drafts."`.

### Task 3: Integrate contradiction output into audit report body

- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** Inside the `Detect drift, build audit body, manage PR` step, in the heredoc that writes `/tmp/audit-body.md`
- **What:** After the existing `## Suggested edits` section, append a `## Contradictions` section that renders each entry from `$AUDIT_CONTRADICTIONS` as a bullet line. After the metrics drift table header, add `(unaudited)` suffix to any metric key present in `$AUDIT_UNAUDITED_METRICS`.
- **Detail:** When `AUDIT_CONTRADICTIONS` is an empty JSON array `[]`, the section renders as `_No contradictions detected in this run._` so the heading always appears (making absence explicit). Each bullet line follows the format: `` `{metric}` green={green_value}: {failure_mode} — {evidence} → **{remedy}** ``. Metric rows in the drift table that appear in `AUDIT_UNAUDITED_METRICS` get their `Verdict` column value suffixed with ` (unaudited)`, e.g., `OK (unaudited)`. Apply this by post-processing `/tmp/rows.jsonl` with `jq` using the unaudited list before rendering the table rows.

### Task 4: Persist contradiction findings in baseline JSON

- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** Inside the `Detect drift, build audit body, manage PR` step, where `current_metrics` JSON object is assembled with `jq -nc`
- **What:** Extend the `current_metrics` object to include a top-level `contradictions` field set to the parsed value of `$AUDIT_CONTRADICTIONS`, and an `unaudited_metrics` field set to the parsed value of `$AUDIT_UNAUDITED_METRICS`.
- **Detail:** This keeps contradiction history queryable from `company/strategy-audit-baseline.json` over time. When `AUDIT_CONTRADICTIONS` is empty, store `[]`. When `AUDIT_UNAUDITED_METRICS` is empty, store `[]`. Pass both via `--argjson` into the existing `jq -nc` invocation that builds `current_metrics`. No schema migration needed — `jq` with `// []` default handles older audit entries that lack these fields.

### Task 5: Update config example to document contradiction schema fields

- **File:** `.compound-engineering/config.local.example.yaml` (modify — this is Task 1's file; they share the same edit pass)
- **Where:** Same block added in Task 1
- **What:** This task is fulfilled by Task 1; documenting the schema inline in the example file is sufficient. No additional file needed.

> _Note: Task 5 is collapsed into Task 1 — both touch the same block of `.compound-engineering/config.local.example.yaml`._

## Affected Files

`.compound-engineering/config.local.example.yaml`   (modify)
`.github/workflows/strategy-audit.yml`               (modify, no-test)

## Test Strategy

- `gh workflow run strategy-audit.yml --ref main` against a window where `autonomous_ship_rate` is positive AND open PRs with `awaiting-verification` label exist; the resulting audit PR body must contain a `## Contradictions` section with at least one bullet naming the stale PR, and the `autonomous_ship_rate` row in the drift table must show `OK (unaudited)` or `DRIFT (unaudited)`.
- Re-run the workflow with `--ref main` on a clean state (no `awaiting-verification` PRs, all issues triaged, `paid_customers` sourced from structured data); the `## Contradictions` section must render `_No contradictions detected in this run._` and no metric row contains `(unaudited)`.
- Inspect `company/strategy-audit-baseline.json` after a run; the most recent audit entry must contain `contradictions` and `unaudited_metrics` top-level keys.
- Sanity check against 2026-05-06 dataset: with one merged bot PR and one `awaiting-verification` PR open, the audit must surface `autonomous_ship_rate` contradiction (`1/1 ship + 1 awaiting-verification`) in the report body.

## Estimated Complexity

medium (2 files, ~150 lines of bash/yaml/jq additions)
