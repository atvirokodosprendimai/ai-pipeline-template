---
title: "Loop PR auto-merge fails due to Copilot review timing race"
category: integration-issues
date: 2026-03-18
tags: [github-actions, observation-loop, copilot-reviewer, auto-merge, polling]
---

## Problem

Daily observation loop PRs intermittently fail to auto-merge. PR #34 (2026-03-18) was left open despite clean Copilot review — the workflow logged `No review received within 90s. Leaving PR #34 open.`

## Root Cause

The observation loop used a **polling strategy** (18 iterations × 5s = 90s) to wait for Copilot's review after PR creation. When Copilot responded slower than 90 seconds — which happened on PR #34 where the review arrived at `08:56:28Z`, ~68s after the polling window expired at `08:55:20Z` — the loop gave up and left the PR open with no retry mechanism.

Polling is fundamentally fragile here because Copilot review latency is unpredictable and varies by load.

## Solution

Replaced polling with an **event-driven** workflow (`loop-automerge.yml`) that triggers on `pull_request_review` events:

```yaml
on:
  pull_request_review:
    types: [submitted]

jobs:
  automerge:
    if: >-
      startsWith(github.event.pull_request.head.ref, 'loop/') &&
      github.event.review.state != 'changes_requested'
```

The workflow checks for blocking reviews and inline comments, then merges if clean. The observation loop now creates the PR and moves on immediately — 43 lines of polling logic removed.

## Prevention

- Prefer event-driven workflows over polling when GitHub provides webhook events for the condition you're waiting on.
- `pull_request_review` event fires regardless of review latency — no timing assumptions needed.
