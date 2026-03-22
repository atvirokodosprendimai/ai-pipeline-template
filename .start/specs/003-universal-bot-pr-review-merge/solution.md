---
title: "Universal Bot PR Review and Merge"
status: draft
version: "1.0"
---

# Solution Design Document

## Constraints

- CON-1: Must not duplicate review-merge for PRs already handled inline
- CON-2: Must filter to approved bot authors before running the script
- CON-3: CONSTITUTION v2.0 compliance (Andon, SEC-1/3/4, ARCH-4/8, QUAL-1/5)
- CON-4: GitHub Actions `pull_request` event has limited token permissions — needs PUSH_TOKEN

## Solution Strategy

**Architecture**: Single event-driven workflow triggered on `pull_request: [opened]`. Filters by author, then calls the existing pr-review-merge.sh. Removes inline calls from pipeline-health.yml and observation-loop.yml to eliminate duplication.

**Why `opened` only (not `synchronize`)**: The fix loop inside pr-review-merge.sh already handles new pushes by polling for the next review. A `synchronize` trigger would cause a second workflow run that races with the in-progress fix loop.

**Deduplication strategy**: Remove inline callers. The universal workflow replaces them — simpler than detecting "already processing" state.

## Architecture Decisions

- [x] **ADR-1: pull_request event trigger**
  - Choice: Trigger on `pull_request: [opened]`
  - Rationale: Catches all PRs at creation. `synchronize` excluded to avoid racing with fix loop.
  - Trade-offs: Won't re-trigger if a PR is manually re-opened after close. Acceptable — edge case.

- [x] **ADR-2: Author filter in workflow `if` condition**
  - Choice: Filter approved authors via `github.event.pull_request.user.login` in the job's `if:` condition
  - Rationale: Skips the entire job (no runner cost) for non-bot PRs. Faster than checking inside the script.
  - Trade-offs: Author list is duplicated between workflow YAML and script env var. Acceptable — the workflow filter is the fast path, script is the authoritative check.

- [x] **ADR-3: Remove inline callers**
  - Choice: Remove pr-review-merge.sh calls from pipeline-health.yml and observation-loop.yml
  - Rationale: Universal workflow handles all bot PRs. Inline calls create duplication risk.
  - Trade-offs: pipeline-health and observation-loop PRs now depend on the universal workflow. If the universal workflow is disabled, those PRs won't auto-merge. Acceptable — the universal workflow is the single source of truth.

## Building Block View

### Directory Map

```
.github/
  workflows/
    bot-pr-review-merge.yml      # NEW: universal trigger
    pipeline-health.yml          # MODIFY: remove inline pr-review-merge.sh call
    observation-loop.yml         # MODIFY: remove inline pr-review-merge.sh call
company/
  scripts/
    pr-review-merge.sh           # UNCHANGED: existing script
```

### Workflow Specification

```yaml
# .github/workflows/bot-pr-review-merge.yml
name: Bot PR Review and Merge

on:
  pull_request:
    types: [opened]

permissions:
  contents: write
  pull-requests: write
  issues: write
  actions: read

concurrency:
  group: pr-review-${{ github.event.pull_request.number }}
  cancel-in-progress: false

jobs:
  review-merge:
    if: >-
      github.event.pull_request.user.login == 'copilot-swe-agent[bot]' ||
      github.event.pull_request.user.login == 'goose[bot]'
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Autonomous PR review and merge
        env:
          GH_TOKEN: ${{ secrets.PUSH_TOKEN }}
          TARGET_REPO: ${{ github.repository }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
        run: |
          bash company/scripts/pr-review-merge.sh
```

### Key Design Details

**Concurrency group**: `pr-review-${{ github.event.pull_request.number }}` — one review-merge process per PR. If the same PR triggers multiple events, only one runs. `cancel-in-progress: false` prevents killing an in-progress review-merge.

**Author filter**: The `if:` condition on the job checks `github.event.pull_request.user.login`. This is safe because `user.login` is set by GitHub (not user-controlled input). It's passed via the event context, not interpolated in `run:` (SEC-3 compliant).

**PR_NUMBER**: Uses `github.event.pull_request.number` passed through `env:` block (SEC-1, SEC-3 compliant).

**Checkout**: Required because pr-review-merge.sh and sanitise.sh live in the repo.

### Changes to Existing Workflows

**pipeline-health.yml**: Remove the 4-line block:
```yaml
          # Autonomous review-merge: ...
          # merge or escalate. ...
          PR_NUMBER="$pr_number" TARGET_REPO="$GITHUB_REPOSITORY" \
            bash company/scripts/pr-review-merge.sh
```
The `pull_request: [opened]` event from `gh pr create` will trigger bot-pr-review-merge.yml.

**observation-loop.yml**: Same removal.

### Constitution Compliance

| Rule | Compliance |
|------|-----------|
| SEC-1 | PUSH_TOKEN via env block |
| SEC-3 | PR number via env, not interpolated in run: |
| SEC-4 | Explicit minimal permissions |
| ARCH-4 v2.0 | Uses pr-review-merge.sh with guardrails |
| ARCH-8 | PUSH_TOKEN, not GITHUB_TOKEN |
| QUAL-5 | Andon handled by pr-review-merge.sh |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Universal workflow disabled → no auto-merge | High | Monitor: if no PRs auto-merge for 24h, alert |
| pull_request event doesn't fire for some bot PRs | Medium | Test with each bot type before removing inline callers |
| Author login format changes | Low | APPROVED_AUTHORS env var in script is the authoritative check |
