---
title: "Observation loop LLM creates bogus issues for features that already exist"
category: logic-errors
date: 2026-03-16
tags: [observation-loop, llm, dedup, codebase-awareness, hallucination]
related_issues:
  - https://github.com/atvirokodosprendimai/wgmesh/issues/458
  - https://github.com/atvirokodosprendimai/wgmesh/issues/453
  - https://github.com/atvirokodosprendimai/wgmesh/issues/460
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

## Post-fix failure: #460 created despite codebase summary

The fixes above were deployed on 2026-03-16 10:48. Yet run 7 (2026-03-17 08:58) still created #460 "Implement basic WireGuard mesh networking core" — a feature that obviously exists.

### Why the fix wasn't enough

The codebase summary was a single new signal competing against compounding reinforcement:

1. **`loop-state.json` still had `funnel_stage: 0`** — nobody advanced it after deploying the fix
2. **Assessment history** (runs 5, 6) both said "No wgmesh core product code exists"
3. The LLM received 1 signal saying "product exists" vs 3 signals saying "no product" (funnel_stage + 2 prior assessments)

Run 7 wrote: *"Engineering velocity remains high but still focused on infrastructure rather than core product"* — it interpreted 28 merged PRs as infra work because its priors were too strong.

Run 8 (2026-03-18) finally self-corrected after accumulating enough evidence.

### Why bogus issues weren't auto-closed

The `issues_to_close` mechanism existed but run 8 (the first to recognize the product) didn't use it for #453, #458, #460 because:

1. These issues had `copilot-triaging` label with Copilot assigned — the LLM interpreted "in progress" as "legitimate"
2. No instruction forced systematic reconciliation of every open issue against the codebase summary
3. The open issues list only shows titles and labels — not enough context for the LLM to determine overlap with existing features without explicit prompting

### Additional fixes (2026-03-18)

1. **Mandatory reconciliation pass** added to system prompt: LLM must check every open `fn:dev` issue against the Product Codebase Summary, regardless of current labels
2. **Override stale assessments** instruction: if codebase summary contradicts prior assessments, trust the code
3. **`stage_entered` timestamp** set in `loop-state.json` to track when stages were entered

## Prevention

- **Any LLM that creates real-world artifacts (issues, PRs, deployments) must have ground-truth context** about what already exists. Metadata alone (counts, velocity) is insufficient — it needs structural awareness.
- When adding new repos to the observation loop, ensure their `CLAUDE.md` (or equivalent) is included in the product summary collection step.
- Periodically verify `loop-state.json` funnel stage reflects reality — a stale stage amplifies LLM hallucination.
- **A single corrective signal is not enough to override compounding priors.** When fixing LLM context, also fix the reinforcing signals (funnel_stage, assessment history) or the LLM will ignore the correction.
- **Mandatory reconciliation beats voluntary cleanup.** LLMs will not systematically cross-reference issues against codebase unless explicitly instructed to do so on every run.
