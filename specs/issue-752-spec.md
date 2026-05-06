# Specification: Issue #752

## Classification
fix

## Deliverables
code

## Problem Analysis

Every GitHub Actions step that calls an external HTTP endpoint (MentisDB, PostHog) can hang the
workflow run indefinitely when the remote service is slow, unreachable, or auth-rejecting. The
confirmed failure mode: `spec-validation.yml` step `Append spec-validation outcome to MentisDB`
blocked six spec PRs in `in_progress` for 3+ hours on 2026-05-06.

Three layers of protection are required at each such step:

1. **Step-level `continue-on-error: true`** — a non-zero shell exit (including from
   `set -euo pipefail`) must not fail the workflow job. External telemetry is supplementary;
   the workflow's primary outcome must be preserved.
2. **Step-level `timeout-minutes: 1`** — the GitHub Actions runner must kill the step after
   60 seconds regardless of what the process does, providing a hard wall-clock cap that cannot
   be bypassed by stuck DNS, TLS handshakes, or retry loops.
3. **Request-level non-fatal curl guard** — `curl ... || { code=$?; echo "::warning::..."; }` —
   already present in most MentisDB steps but missing in `observation-loop.yml`.

**Current gaps per workflow file (as verified in the repository):**

| Workflow file | Step name | Missing `continue-on-error` | Missing `timeout-minutes` | Missing non-fatal curl guard | Missing `if: always()` |
|---|---|---|---|---|---|
| `spec-validation.yml` | `Append spec-validation outcome to MentisDB` | ✗ | ✗ | — | — |
| `bot-pr-review-merge.yml` | `Append review-merge outcome to MentisDB` | ✗ | ✗ | — | — |
| `heartbeat-pr-automerge.yml` | `Append heartbeat-merge outcome to MentisDB` | ✗ | ✗ | — | — |
| `copilot-triage.yml` | `Append issue-triage outcome to MentisDB` | ✗ | ✗ | — | — |
| `copilot-undraft.yml` | `Append undraft outcome to MentisDB` | ✗ | ✗ | — | — |
| `approve-build.yml` | `Append spec-approval outcome to MentisDB` (both jobs) | ✗ | ✗ | — | — |
| `spec-merged-build.yml` | `Append spec-merge-build outcome to MentisDB` | ✗ | ✗ | — | — |
| `impl-merged-close.yml` | `Append impl-close outcome to MentisDB` | ✗ | ✗ | — | — |
| `pipeline-health.yml` | `Append pipeline-health outcome to MentisDB` | ✗ | ✗ | — | — |
| `strategy-audit.yml` | `Append audit outcome to MentisDB` | ✗ | ✗ | — | — |
| `health-check.yml` | `Append endpoint-health failure to MentisDB` | ✗ | ✗ | — | — |
| `observation-loop.yml` | `Append assessment to MentisDB` | ✗ | ✗ | ✗ | ✗ |
| `bot-pr-review-merge.yml` | `Emit bot_pr_merged to PostHog` | ✗ | ✗ | — | — |
| `pipeline-health.yml` | `Emit pipeline_health_run to PostHog` | ✗ | ✗ | — | — |
| `strategy-audit.yml` | `Emit strategy_audit_run to PostHog` | ✗ | ✗ | — | — |

`mentisdb-smoketest.yml` is intentionally left fatal — its purpose is to validate MentisDB
itself, so failures must surface. `terraform-deploy.yml` uses `MENTISDB_PASSWORD` only for
infrastructure variables and does not emit HTTP calls to the thoughts API; no change needed.

A CI lint script (`company/scripts/check-external-call-guards.sh`) does not yet exist, so
nothing prevents future PRs from re-introducing unguarded external-service steps.

The pattern reference document (`memory/reference_mentisdb_ci_integration_pattern.md`) omits
`continue-on-error: true` and `timeout-minutes: 1` from its canonical step template, which
is why the pattern was never applied consistently.

## Implementation Tasks

### Task 1: Harden MentisDB append step in `spec-validation.yml`

- **File:** `.github/workflows/spec-validation.yml` (modify)
- **Where:** The step named `Append spec-validation outcome to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` as new fields immediately
  after the existing `if: always()` field of that step. No other changes to this step.
- **Detail:** The step already contains `if: always()`, `--max-time 15` in the curl command,
  and the non-fatal curl guard `|| { code=$?; echo "::warning::mentisdb append failed (curl exit $code, non-fatal)"; }`.
  Only the two step-level YAML fields are missing. After the change the step header should read:

  ```yaml
  - name: Append spec-validation outcome to MentisDB
    if: always()
    continue-on-error: true
    timeout-minutes: 1
    env:
  ```

### Task 2: Harden MentisDB append step in `bot-pr-review-merge.yml`

- **File:** `.github/workflows/bot-pr-review-merge.yml` (modify)
- **Where:** The step named `Append review-merge outcome to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** Same pattern as Task 1. The non-fatal curl guard and `--max-time 15` are already
  present. Only the two step-level YAML fields are missing.

### Task 3: Harden MentisDB append step in `heartbeat-pr-automerge.yml`

- **File:** `.github/workflows/heartbeat-pr-automerge.yml` (modify)
- **Where:** The step named `Append heartbeat-merge outcome to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** Same pattern as Task 1.

### Task 4: Harden MentisDB append step in `copilot-triage.yml`

- **File:** `.github/workflows/copilot-triage.yml` (modify)
- **Where:** The step named `Append issue-triage outcome to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** Same pattern as Task 1.

### Task 5: Harden MentisDB append step in `copilot-undraft.yml`

- **File:** `.github/workflows/copilot-undraft.yml` (modify)
- **Where:** The step named `Append undraft outcome to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** Same pattern as Task 1.

### Task 6: Harden MentisDB append steps in `approve-build.yml`

- **File:** `.github/workflows/approve-build.yml` (modify)
- **Where:** Both steps named `Append spec-approval outcome to MentisDB` (one per job in the
  file; both need the change)
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of each step.
- **Detail:** Same pattern as Task 1. Apply to both occurrences.

### Task 7: Harden MentisDB append step in `spec-merged-build.yml`

- **File:** `.github/workflows/spec-merged-build.yml` (modify)
- **Where:** The step named `Append spec-merge-build outcome to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** Same pattern as Task 1.

### Task 8: Harden MentisDB append step in `impl-merged-close.yml`

- **File:** `.github/workflows/impl-merged-close.yml` (modify)
- **Where:** The step named `Append impl-close outcome to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** Same pattern as Task 1.

### Task 9: Harden MentisDB append step in `pipeline-health.yml`

- **File:** `.github/workflows/pipeline-health.yml` (modify)
- **Where:** The step named `Append pipeline-health outcome to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** Same pattern as Task 1.

### Task 10: Harden MentisDB append step in `strategy-audit.yml`

- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** The step named `Append audit outcome to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** Same pattern as Task 1.

### Task 11: Harden MentisDB append step in `health-check.yml`

- **File:** `.github/workflows/health-check.yml` (modify)
- **Where:** The step named `Append endpoint-health failure to MentisDB`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if:` condition of that step (`if: steps.health.outputs.down_count != '0'`).
- **Detail:** Same pattern as Task 1, but preserving the existing non-`always()` condition.

### Task 12: Harden MentisDB append step in `observation-loop.yml` (most severe gaps)

- **File:** `.github/workflows/observation-loop.yml` (modify)
- **Where:** The step named `Append assessment to MentisDB`
- **What:** Four changes to this step:
  1. Add `if: always()` as the first field after the step `name`.
  2. Add `continue-on-error: true` immediately after `if: always()`.
  3. Add `timeout-minutes: 1` immediately after `continue-on-error: true`.
  4. Add a non-fatal guard to the curl command at the end of the step's `run` block.
     Replace the bare `curl ... "$URL"` final line with:
     `curl ... "$URL" || { code=$?; echo "::warning::mentisdb append failed (curl exit $code, non-fatal)"; }`
- **Detail:** Unlike all other MentisDB append steps, this one currently has no `if: always()`
  (it is skipped when prior steps fail), no `continue-on-error: true`, no `timeout-minutes`,
  and the curl exits fatally without a `||` guard. The sanitise.sh `exit 1` gates (which check
  content before POSTing) may keep their `::error::` annotations and `exit 1` — with
  `continue-on-error: true` at the step level these will show as step warnings without
  failing the job. Only the curl line at the end of the `run` block needs the non-fatal guard
  added. The `MENTISDB_URL`, `MENTISDB_USER`, and `MENTISDB_PASSWORD` env vars already exist
  on the step.

### Task 13: Harden PostHog emit step in `bot-pr-review-merge.yml`

- **File:** `.github/workflows/bot-pr-review-merge.yml` (modify)
- **Where:** The step named `Emit bot_pr_merged to PostHog`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** `posthog-emit.sh` already has `--max-time 10` and a non-fatal guard internally.
  Only the step-level YAML fields are missing.

### Task 14: Harden PostHog emit step in `pipeline-health.yml`

- **File:** `.github/workflows/pipeline-health.yml` (modify)
- **Where:** The step named `Emit pipeline_health_run to PostHog`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always()` field of that step.
- **Detail:** Same as Task 13.

### Task 15: Harden PostHog emit step in `strategy-audit.yml`

- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** The step named `Emit strategy_audit_run to PostHog`
- **What:** Add `continue-on-error: true` and `timeout-minutes: 1` immediately after the
  existing `if: always() && steps.skip-guard.outputs.skip != 'true'` field of that step.
- **Detail:** Same as Task 13.

### Task 16: Create workflow lint script `company/scripts/check-external-call-guards.sh`

- **File:** `company/scripts/check-external-call-guards.sh` (create)
- **Where:** New file, executable (`chmod +x`)
- **What:** A bash script that scans all YAML files in `.github/workflows/` (or a directory
  passed as `$1`) and reports any `run:` block that contains a `curl` call to an HTTP/HTTPS URL
  but whose enclosing step is missing either `continue-on-error: true` or `timeout-minutes`.
  Exit 0 if no violations; exit 1 with a descriptive error message per violation.
- **Detail:** The script must use `set -euo pipefail`. It should parse each workflow YAML
  using line-based heuristics (no external YAML parser required): a step boundary is a line
  matching `^\s+- name:` or `^\s+- uses:`; within each step block, detect presence of
  `continue-on-error:` and `timeout-minutes:` fields; the step body's `run:` content is
  detected by the presence of `curl` with an http/https URL pattern (`https?://` or
  variable expansions like `$MENTISDB_URL`, `$POSTHOG_HOST`, `$URL`). Exempt steps whose
  name matches `smoketest` (mentisdb-smoketest.yml is intentionally fatal). Report violations
  as `FAIL: <file>: step "<step-name>" calls curl but missing: <field-list>`. Run in CI on
  any PR that modifies a `.github/workflows/*.yml` file.

### Task 17: Create workflow to run the lint check on PRs

- **File:** `.github/workflows/lint-external-call-guards.yml` (create)
- **Where:** New file
- **What:** A GitHub Actions workflow that triggers on `pull_request` for paths
  `.github/workflows/*.yml` and `company/scripts/check-external-call-guards.sh`, checks out
  the repository, and runs `bash company/scripts/check-external-call-guards.sh .github/workflows/`.
  The job must fail if the script exits non-zero.
- **Detail:** Use `ubuntu-latest`, `actions/checkout@v4`, minimal permissions
  (`contents: read`). No secrets required. The workflow name should be
  `Lint: External Call Guards`. Job id `lint`. Single step after checkout:
  `bash company/scripts/check-external-call-guards.sh .github/workflows/`.

### Task 18: Update `memory/reference_mentisdb_ci_integration_pattern.md`

- **File:** `memory/reference_mentisdb_ci_integration_pattern.md` (modify)
- **Where:** The `## Failure Policy` section, in the bash code block showing the canonical
  curl pattern
- **What:** Expand the example step snippet to show the full YAML step with
  `continue-on-error: true` and `timeout-minutes: 1`. Add a new sub-section
  `## Required Step Fields` that lists the mandatory YAML fields for any non-fatal
  MentisDB append step: `if: always()`, `continue-on-error: true`, `timeout-minutes: 1`.
- **Detail:** The current document shows only the `curl` bash snippet but does not document
  the enclosing YAML step fields. An implementer reading only this document must be able to
  produce a fully compliant step. Add the following after the existing `## Failure Policy`
  curl snippet:

  ```
  ## Required Step Fields

  Every non-fatal MentisDB append step must include all three YAML fields:

  ```yaml
  - name: Append <event> to MentisDB
    if: always()
    continue-on-error: true
    timeout-minutes: 1
    env:
      ...
  ```

  - `if: always()` — run even if prior steps failed; telemetry must not depend on success
  - `continue-on-error: true` — a non-zero shell exit must not fail the job
  - `timeout-minutes: 1` — hard runner-level cap; prevents indefinite hangs even when curl's
    `--max-time` is bypassed (e.g. stuck DNS, TLS handshake, runner-level hang)
  ```

## Affected Files

`.github/workflows/spec-validation.yml`            (modify)
`.github/workflows/bot-pr-review-merge.yml`        (modify)
`.github/workflows/heartbeat-pr-automerge.yml`     (modify)
`.github/workflows/copilot-triage.yml`             (modify)
`.github/workflows/copilot-undraft.yml`            (modify)
`.github/workflows/approve-build.yml`              (modify)
`.github/workflows/spec-merged-build.yml`          (modify)
`.github/workflows/impl-merged-close.yml`          (modify)
`.github/workflows/pipeline-health.yml`            (modify)
`.github/workflows/strategy-audit.yml`             (modify)
`.github/workflows/health-check.yml`               (modify)
`.github/workflows/observation-loop.yml`           (modify)
`.github/workflows/lint-external-call-guards.yml`  (new)
`company/scripts/check-external-call-guards.sh`    (new)
`memory/reference_mentisdb_ci_integration_pattern.md` (modify)

## Test Strategy

- `bash .github/scripts/validate-spec.sh specs/issue-752-spec.md` passes with zero FAILs.
- After implementation, `bash company/scripts/check-external-call-guards.sh .github/workflows/` exits 0 (no violations).
- Verify: `grep -r "continue-on-error" .github/workflows/` returns every MentisDB append and PostHog emit step listed in the Problem Analysis table.
- Verify: `grep -r "timeout-minutes: 1" .github/workflows/` returns every MentisDB append and PostHog emit step listed above (mentisdb-smoketest.yml has `timeout-minutes: 5` at job level and must not appear in the per-step search).
- Verify: `.github/workflows/observation-loop.yml` step `Append assessment to MentisDB` now contains `if: always()`, `continue-on-error: true`, `timeout-minutes: 1`, and `|| { code=$?; echo "::warning::mentisdb append failed` in its `run` block.
- Verify: The new workflow `lint-external-call-guards.yml` triggers on a test branch that introduces an unguarded `curl` step and the lint job fails.

## Estimated Complexity
high
