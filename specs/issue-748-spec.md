# Specification: Issue #748

## Classification
fix

## Deliverables
code

## Problem Analysis

When an issue is reopened (`issues: reopened` event), the triage pipeline does not re-engage.
`copilot-triage.yml` fires on `issues: labeled` — it requires a pipeline-entry label
(`needs-triage`, `fn:dev`, or `bug`) to be applied _after_ the reopen. No workflow currently
applies such a label on reopen, so reopened issues sit indefinitely without `copilot-triaging`,
no spec PR, and no pipeline movement.

Stale labels from a previous pipeline cycle (`awaiting-verification`, `verified`,
`copilot-triaging`, `spec-ready`, `approved-for-build`, `goose-implementation`, `needs-review`)
may still be present on the issue when it is reopened. They falsely imply the issue is in a
healthy state and must be stripped before triage restarts.

There is no guard in the pulse / observation-loop to surface reopened issues that lack
`copilot-triaging` after one hour. This is deferred to issue #742 per the issue's Related
section, but the label cleanup and re-triage trigger are in scope here.

## Implementation Tasks

### Task 1: New reopen-handler workflow

- **File:** `.github/workflows/issue-reopened.yml` (create)
- **Where:** New file
- **What:** A workflow named `Issue Reopened — Re-trigger Triage` that fires on `issues: reopened`, strips stale pipeline labels, and applies `needs-triage` to re-enter the existing triage pipeline.
- **Detail:**
  The workflow must check whether the issue already has `copilot-triaging` at the moment the
  reopen fires; if it does, skip silently to prevent a double-assignment race with any in-flight
  triage job. Otherwise, attempt to remove each of the following labels (ignore 404 — they may
  not all be present): `awaiting-verification`, `verified`, `copilot-triaging`, `spec-ready`,
  `approved-for-build`, `goose-implementation`, `needs-review`. Then add `needs-triage`.
  This re-entry label causes `copilot-triage.yml` to fire as normal. Post a comment on the issue
  stating that it was reopened and triage has been re-triggered. Append an outcome record to
  MentisDB (matching the pattern used in `copilot-triage.yml`'s "Append issue-triage outcome"
  step) using `agent_id: "issue-reopened"`.

  Required permissions: `issues: write`, `contents: read`.
  Use `secrets.PUSH_TOKEN` for the `github-token` in `actions/github-script@v8` (same as
  `copilot-triage.yml`).

  The skip guard must use `contains(join(...), 'copilot-triaging')` on
  `github.event.issue.labels` to match the pattern already used in `copilot-triage.yml`'s
  `if:` condition.

### Task 2: Add `awaiting-verification` and `verified` label definitions

- **File:** `.github/labels.yml` (modify)
- **Where:** After the `needs-human` entry, inside the `# === Health Monitoring ===` section or a new `# === Verification Labels ===` section
- **What:** Add label definitions for `awaiting-verification` and `verified` so they can be created in the target repo and cleaned up reliably on reopen.
- **Detail:**
  `awaiting-verification`: color `"FEF2C0"`, description `"Fix merged; waiting for e2e verification"`.
  `verified`: color `"0E8A16"`, description `"Fix confirmed by automated e2e verification"`.
  These must be present in `labels.yml` so that `sync-labels.yml` provisions them on push to
  `main`, and the reopen handler can remove them without a 404 in repos that have already synced
  labels. The removal in the reopen workflow must still use a try/catch to remain idempotent in
  repos that haven't synced yet.

## Affected Files

`.github/workflows/issue-reopened.yml`   (new)
`.github/labels.yml`                     (modify)

## Test Strategy

- Open a test issue in the repo, apply `needs-triage` label, wait for `copilot-triaging` to be
  applied, then close the issue. Manually reopen it. Within two minutes (typical GitHub Actions
  queue + execution time for a lightweight label-management job) the following must hold:
  - `copilot-triaging`, `spec-ready`, `approved-for-build` and any other stale pipeline labels
    are absent.
  - `needs-triage` is present (re-applied by the reopen handler).
  - A comment from the workflow bot is visible on the issue.
  - `copilot-triage.yml` has a new successful run triggered by the `needs-triage` label event.
- Reopen the issue a second time after the above run completes: a second `copilot-triaging`
  assignment must appear, confirming idempotency.
- Manually dispatch `sync-labels.yml` after the `labels.yml` change and verify that
  `awaiting-verification` and `verified` labels are created in the repo.
- Verify the MentisDB curl step logs a non-failure (or gracefully warns) when
  `MENTISDB_URL` is absent (matches existing workflow behaviour).

## Estimated Complexity
low (2 files, ~80 lines)
