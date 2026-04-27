---
title: "GitHub App reviews do not trigger pull_request_review workflow events"
category: integration-issues
date: 2026-03-22
tags: [github-actions, github-apps, copilot-reviewer, auto-merge, security-model]
---

## Problem

`loop-automerge.yml` had **zero successful runs** in its entire history. 10+ loop assessment PRs (#40-50) piled up without being merged, despite each receiving a Copilot review. The workflow triggers on `pull_request_review: types: [submitted]`, but no run ever appeared — even though the PullRequestReviewEvent was visible in the repository `/events` API.

## Root Cause

GitHub Apps (such as `copilot-pull-request-reviewer[bot]`) that authenticate with `GITHUB_TOKEN` **cannot trigger workflow events**. This is a deliberate GitHub security feature designed to prevent recursive workflow triggers — an App-initiated action never fires the corresponding webhook for GitHub Actions.

Copilot reviewer submits `COMMENTED` reviews with inline comments. The review itself is recorded (it appears in the PR timeline and the `/events` API), but GitHub silently skips the `pull_request_review` workflow trigger because the actor is a GitHub App.

This means the event-driven auto-merge architecture introduced to replace polling (see `loop-pr-automerge-timing-race.md`) was **never operational** — the trigger condition could never be satisfied by the only reviewer configured for these PRs.

### Investigation timeline

1. Checked PR #52 reviews — Copilot reviewed at 09:15, auto-merge fix deployed at 09:23.
2. No auto-merge run appeared for PR #54 despite Copilot review at 10:36.
3. Queried `/events` API — `PullRequestReviewEvent` exists for both PRs, but no corresponding workflow run was created.
4. Verified zero successful `loop-automerge.yml` runs across the entire repository history.
5. Conclusion: GitHub Apps authenticating via `GITHUB_TOKEN` do not trigger `pull_request_review` events for workflows.

### Secondary issue (moot)

Bot inline comments were also blocking the merge logic (fixed in PR #51). However, this fix was irrelevant because the workflow never triggered in the first place.

## Solution

Removed the dependency on external review events. Workflows now **self-merge their own PRs** directly after validation, eliminating the need for a separate `pull_request_review`-triggered workflow entirely (PRs #55, #57). The dead `loop-automerge.yml` workflow file was deleted in PR #67.

Current implementation: [`.github/workflows/heartbeat-pr-automerge.yml`](../../../.github/workflows/heartbeat-pr-automerge.yml) triggers on `pull_request: [opened, reopened, synchronize]`, validates `loop:`/`heal:` titled PRs against scope checks (same-repo, not a fork, allowed bot author, file allowlist), and merges directly. No external review event dependency.

## Prevention

- Never rely on GitHub App actions (reviews, comments, status checks) to trigger downstream workflows. The `GITHUB_TOKEN` security boundary silently suppresses these events.
- When designing automation chains, verify that the actor producing the trigger event is a **user or a Personal Access Token** — not a GitHub App token. App-generated events are visible in the API but invisible to Actions.
- Test workflow trigger conditions end-to-end with the actual actor; unit-testing the workflow logic alone will not reveal this class of silent failure.
