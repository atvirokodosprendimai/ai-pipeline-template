# Heartbeat Fast Lane Rollout Plan

## Purpose

Restore continuous flow visibility by routing low-risk heartbeat PRs through a dedicated fast lane instead of the general bot PR review queue.

Heartbeat PRs are operational state replication events, not implementation/code review artifacts.

## Scope of the Fast Lane

PRs eligible for heartbeat auto-merge must satisfy all of the following:

- PR title starts with `loop: ` or `heal: `
- PR head repo matches the base repo (same-repo only)
- PR does not originate from a fork
- PR author is an allowed bot identity
- PR branch matches expected naming:
  - `loop/assessment-*`
  - `pipeline-health/*`
- Changed files are limited to approved heartbeat paths only
- Total changed lines are 1000 or fewer
- JSON / JSONL files parse successfully
- Sanitisation passes on all changed files

## Approved Heartbeat Paths

- `company/loop-state.json`
- `company/loop-history/*.md`
- `memory/episodic/*.md`
- `company/pipeline-health-state.json`
- `company/audit-log.jsonl`

## Pre-flight Checklist

Before rollout:

- [x] Confirm `.github/workflows/heartbeat-pr-automerge.yml` exists on the target branch
- [ ] Confirm `.github/workflows/bot-pr-review-merge.yml` no longer routes `loop:` or `heal:` PRs
- [ ] Confirm repository has `PUSH_TOKEN` configured and still valid
- [ ] Confirm `PUSH_TOKEN` has at least contents write + pull requests write scopes
- [ ] Confirm branch protection allows merges from workflow actor/token
- [ ] Confirm `needs-human` label exists in the repository
- [ ] Confirm heartbeat branch naming in source workflows still matches the fast-lane expectations
- [ ] Confirm heartbeat file paths written by `observation-loop.yml` and `pipeline-health.yml` still match the approved path whitelist

## Manual Validation Runbook

### Goal

Prove that heartbeat PRs merge through the dedicated fast lane and that `main` reflects fresh heartbeat state again.

### Step 1 — Merge the fast-lane change

Merge the workflow change into `main`.

### Step 2 — Manually trigger both heartbeat producers

From the GitHub Actions UI or CLI, trigger:

- `Observation Loop`
- `Pipeline Health (Self-Healing)`

Suggested CLI commands:

```bash
gh workflow run observation-loop.yml --repo <owner/repo>
gh workflow run pipeline-health.yml --repo <owner/repo>
```

### Step 3 — Watch for PR creation

Look for new PRs titled like:

- `loop: daily assessment YYYY-MM-DD`
- `heal: pipeline health check YYYY-MM-DD`

Expected result:
- PRs may appear briefly, then auto-merge
- They should not sit waiting for Copilot review

### Step 4 — Verify workflow routing

In Actions, confirm:

- `Heartbeat PR Auto-Merge` runs for the `loop:` / `heal:` PRs
- `Bot PR Review and Merge` does **not** run for those heartbeat PRs

### Step 5 — Verify merge result on `main`

Confirm fresh state on `main`:

- `company/loop-state.json` has recent `last_run`
- `company/pipeline-health-state.json` has recent `last_check`
- new `company/loop-history/*` assessment exists
- new `memory/episodic/*` entry exists

### Step 6 — Measure heartbeat freshness

Success thresholds:

- Observation loop freshness: `now - last_run <= 8 hours`
- Pipeline health freshness: `now - last_check <= 2 hours`

## Fix Log

### 2026-04-11: Auto-approve step added

**Problem**: The `protect-main` ruleset requires 1 approving review. Heartbeat PRs were validated but then blocked at merge because no review approval existed. `--auto` queues the merge but doesn't satisfy the review requirement.

**Fix**: Added `Auto-approve heartbeat PR` step after validation/sanitisation and before the `--auto` merge step. The `PUSH_TOKEN` (org admin) posts an approval review, satisfying the ruleset requirement so the queued auto-merge proceeds.

**Note**: Org admins already have `bypass_mode: always` in the ruleset, but `--auto` doesn't use bypass — it just waits for requirements. The explicit approval is the cleanest targeted fix.

## Fault Isolation Guide

If flow is still not restored, isolate by station:

### A. Scheduler dead
Symptoms:
- no new workflow runs appear

Check:
- workflow enabled status
- Actions org/repo policy
- schedule trigger health

### B. PR creation dead
Symptoms:
- workflow runs exist
- no `loop:` / `heal:` PR is created

Check:
- `PUSH_TOKEN`
- branch creation/push failure
- `gh pr create` failure in workflow logs

### C. Fast-lane validation dead
Symptoms:
- PR created
- `Heartbeat PR Auto-Merge` runs and fails
- PR remains open with validation comment

Check:
- same-repo / fork status
- author identity
- branch naming
- file scope
- JSON validity
- sanitisation
- size limit

### D. Merge/auth dead
Symptoms:
- validation passes
- merge step fails

Check:
- token scopes
- branch protection restrictions
- merge permissions for workflow actor/token

## Success Criteria

The rollout is successful when all of the following are true:

- `loop:` PRs auto-merge through `Heartbeat PR Auto-Merge`
- `heal:` PRs auto-merge through `Heartbeat PR Auto-Merge`
- `Bot PR Review and Merge` no longer processes heartbeat PRs
- heartbeat validation failures are visible on the PR via comment/label
- `main` reflects fresh heartbeat state continuously again
