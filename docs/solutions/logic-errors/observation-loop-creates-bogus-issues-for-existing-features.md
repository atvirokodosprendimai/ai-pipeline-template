---
title: "Observation loop LLM creates bogus issues for features that already exist"
category: logic-errors
date: 2026-03-16
tags: [observation-loop, llm, dedup, codebase-awareness, hallucination]
related_issues:
  - https://github.com/atvirokodosprendimai/wgmesh/issues/458
  - https://github.com/atvirokodosprendimai/wgmesh/issues/453
severity: high
component: observation-loop
---

# Observation loop LLM creates bogus issues for features that already exist

## Problem

The daily observation loop LLM assessed wgmesh as having "no core product code" and created greenfield issues (#458 "Implement basic peer discovery", #453 "Define MVP specification") for features that have been shipping for months (4 discovery layers, NAT traversal, gossip, encryption, RPC, relay routing).

## Root Cause

Three compounding gaps:

1. **No codebase visibility.** The LLM received only GitHub API metadata (issue counts, PR velocity, stars) — zero information about what the code actually contains. It could not distinguish "no open issues" from "no product."

2. **Funnel stage stuck at Foundation.** `loop-state.json` had `funnel_stage: 0` ("The core product doesn't exist yet"), reinforcing the LLM's incorrect belief. Nobody had advanced it.

3. **Dedup only checked open issues.** The issue creation step (`observation-loop.yml:324`) fetched only open issue titles for duplicate detection. Implemented-and-closed features like peer discovery passed the filter because their issues were closed.

## Solution

### 1. Inject product codebase summary into LLM prompt

New workflow step fetches `CLAUDE.md` from the primary product repo and includes the architecture section in the user message:

```yaml
# observation-loop.yml — new step after "Collect contribution signals"
- name: Collect product codebase summary
  env:
    GITHUB_TOKEN: ${{ secrets.PUSH_TOKEN }}
  run: |
    primary="atvirokodosprendimai/wgmesh"
    claude_md=$(gh api "repos/$primary/contents/CLAUDE.md" \
      --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    if [ -n "$claude_md" ]; then
      echo "$claude_md" | sed -n '1,/^## Code Conventions/p' | \
        head -n -1 > /tmp/product_summary.txt
    else
      echo "No CLAUDE.md found in $primary." > /tmp/product_summary.txt
    fi
```

The summary is injected into the LLM user message with an explicit instruction:
> "This is the actual state of the primary product repo. Do NOT create issues for features listed here."

### 2. Expand dedup to include closed issues

```yaml
# Before (only open):
gh issue list --repo "$TARGET_REPO" --state open --limit 100 ...

# After (open + closed):
gh issue list --repo "$TARGET_REPO" --state open --limit 200 ...
gh issue list --repo "$TARGET_REPO" --state closed --limit 200 ...
```

### 3. Add explicit guardrail in system prompt

New section in `company/system-prompt.md`:
> **NEVER create issues for features that already exist in the codebase.** Before adding anything to `issues_to_create`, verify it is not already described in the Product Codebase Summary. If no summary is provided, state this as a blocker rather than assuming the product doesn't exist.

## Prevention

- **Any LLM that creates real-world artifacts (issues, PRs, deployments) must have ground-truth context** about what already exists. Metadata alone (counts, velocity) is insufficient — it needs structural awareness.
- When adding new repos to the observation loop, ensure their `CLAUDE.md` (or equivalent) is included in the product summary collection step.
- Periodically verify `loop-state.json` funnel stage reflects reality — a stale stage amplifies LLM hallucination.
