---
title: "Bootstrapping the autonomous review-merge pipeline"
category: integration-issues
date: 2026-03-22
tags: [ooda-loop, pr-review-merge, copilot, guardrails, pipeline-automation]
severity: high
components: [pr-review-merge.sh, bot-pr-review-merge.yml, observation-loop.yml, system-prompt.md]
---

## Problem

The AI pipeline automated issue triage, spec writing, and code generation but had no autonomous review or merge. Bot-authored PRs sat for days waiting for human action. Building the automation exposed 8 distinct bugs during bootstrap.

## Root Cause

The pipeline was a linear chain with manual gaps, not a closed OODA loop. Each gap required a separate fix, and each fix introduced its own integration issues.

## Bugs Encountered and Fixes

### 1. Raw JSON spilling into Actions logs
- **Symptom**: `gh api` and `gh pr view` dumped full JSON responses to workflow logs
- **Fix**: Add `>/dev/null 2>&1` to all `gh` calls that don't need output (PR #83)

### 2. Infinite retry loop from null commit author
- **Symptom**: `check_manual_push()` returned empty author for GitHub Actions commits, triggering false "manual push detected" every iteration, resetting retry counter to 0 forever
- **Fix**: Handle `null`/empty author with `// empty` jq filter, skip reset when author unknown (PR #83)

### 3. Security keyword `key` too broad
- **Symptom**: Assessment PRs containing normal English word "key" (e.g., "key decisions") escalated as security violations
- **Fix**: Remove `key` from SECURITY_KEYWORDS default, keep specific `api_key`, `private_key`. Add `credentials`, `authorization` (PR #87)

### 4. Script checked out from PR branch, not main
- **Symptom**: Fixes to `pr-review-merge.sh` on main didn't take effect because `bot-pr-review-merge.yml` checked out the PR branch (which had the old script)
- **Fix**: `uses: actions/checkout@v4` with `ref: main` (PR #88)

### 5. Resolved review threads counted as blocking
- **Symptom**: Copilot left a review comment, we resolved it, but the script still counted it as an unresolved comment because REST API `/pulls/{pr}/comments` returns all comments regardless of resolution
- **Fix**: Switch to GraphQL API with `reviewThreads` and `isResolved` filter (PR #91)

### 6. Copilot author name mismatch
- **Symptom**: `bot-pr-review-merge.yml` filtered for `copilot-swe-agent[bot]` but Copilot coding agent PRs have `user.login == 'Copilot'`
- **Fix**: Add `'Copilot'` to the workflow `if:` condition (PR #96)

### 7. LLM assessment not creating issues
- **Symptom**: Observation loop identified top actions but left `issues_to_create` empty — pipeline was inert
- **Fix**: Added "Critical rule" to system prompt: every `fn:dev` top action MUST have a corresponding issue (PR #92)

### 8. Race condition on spec validation
- **Symptom**: `pr-review-merge.sh` could merge a spec PR before `spec-validation.yml` finished (label not yet applied)
- **Fix**: Positive gate — require `approved-for-build` label before merging spec PRs, poll up to 3 min for validation to complete (PR #78)

## Prevention

1. **Test with real PRs early** — unit tests with mocked `gh` don't catch API response format issues, author name mismatches, or race conditions between workflows
2. **Check out main for pipeline scripts** — pipeline infrastructure must always run from main, not from the PR branch being processed
3. **Use GraphQL for review thread status** — REST API lacks resolved/unresolved distinction
4. **Security keywords must be specific** — broad words like "key" or "token" cause false positives on non-code PRs (assessments, docs)
5. **Deploy to all observed repos** — the pipeline only works where it's deployed; observing a repo without deploying the pipeline creates a gap

## Related

- [github-app-reviews-dont-trigger-workflows.md](github-app-reviews-dont-trigger-workflows.md) — why polling is required
- [loop-pr-automerge-timing-race.md](loop-pr-automerge-timing-race.md) — predecessor timing issue
- `.start/specs/002-autonomous-pr-review-and-merge/` — original spec
- `.start/specs/003-close-the-ooda-loop/` — full loop closure spec
