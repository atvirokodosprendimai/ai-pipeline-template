---
title: "Observation loop board hygiene — 4 systemic gaps causing issue accumulation"
category: logic-errors
date: 2026-03-19
tags: [observation-loop, dedup, reconciliation, needs-human, cross-repo, board-hygiene]
related_issues:
  - https://github.com/atvirokodosprendimai/wgmesh/issues/463
  - https://github.com/atvirokodosprendimai/wgmesh/issues/448
  - https://github.com/atvirokodosprendimai/wgmesh/issues/336
  - https://github.com/atvirokodosprendimai/wgmesh/issues/454
  - https://github.com/atvirokodosprendimai/wgmesh/issues/428
  - https://github.com/atvirokodosprendimai/wgmesh/issues/455
  - https://github.com/atvirokodosprendimai/wgmesh/issues/418
severity: medium
component: observation-loop
---

# Observation loop board hygiene — 4 systemic gaps causing issue accumulation

## Problem

The wgmesh issue board accumulated 20 open issues over 8 loop runs. Manual audit found 12 were bogus, stale, duplicate, or already fulfilled. The loop created issues it shouldn't have and failed to close issues it should have. Board noise drowned real work signals.

## Root Causes

### 1. Reconciliation only targeted `fn:dev` issues

The mandatory reconciliation pass checked `fn:dev` issues against the codebase summary but ignored `needs-human` issues entirely. Fulfilled requests (#463 funnel stage, #454 available_capital, #428 API access, #455 infra outages) persisted indefinitely because nobody checked if they'd been resolved.

### 2. Fuzzy dedup too coarse for rephrased asks

The dedup extracted only 3 keywords with a narrow stop word list. #444 ("configure monthly burn") and #448 ("review and approve monthly burn") shared the same intent but used different verbs. With only 3 keywords and "configure/review/approve" not in the stop list, matches were fragile.

### 3. No cross-repo issue awareness

#336 (chimney org repo discovery) was filed in wgmesh before chimney had its own repo. When chimney was split out and chimney#1 created, #336 in wgmesh was never closed. The loop's board snapshot only included wgmesh issues — it couldn't detect cross-repo duplicates.

### 4. Stale `needs-triage` labels invisible

Issues #443, #442, #395, #349 had `needs-triage` labels but no Copilot assignee. The triage workflow fired on the original `labeled` event but failed silently (or ran before the workflow existed). GitHub Actions `labeled` events are one-shot — no retry mechanism existed.

## Solution

### Expanded reconciliation (system prompt)

```markdown
**For every open `needs-human` issue:**
1. Check current state (loop-state.json, costs.json, signals) for fulfillment
2. If fulfilled → add to `issues_to_close`
3. If another issue makes the same request differently → close older as superseded

**For every open issue filed in this repo that belongs in a secondary repo:**
1. If corresponding issue exists in secondary repo → close as cross-repo duplicate
```

### Improved fuzzy dedup (observation-loop.yml)

- Keywords: 3 → 5
- Expanded stop words: added `review`, `approve`, `implement`, `basic`, `define`, `fix`, `enable`
- Applied to both `issues_to_create` and `needs_human` dedup blocks

### Cross-repo board snapshot (observation-loop.yml)

Secondary repo open issues (chimney, lighthouse, tvcentras) now included in the board snapshot sent to the LLM.

### Stale triage sweep (observation-loop.yml)

New step after "Close PRs from assessment" that finds issues with `needs-triage` label older than 24h and re-triggers triage by cycling the label.

## Results

Board went from 20 → 8 open issues. Closed 12:
- 3 bogus (features already exist): #453, #458, #460
- 3 bogus PRs: #456, #459, #462
- 3 fulfilled needs-human: #454, #428, #455
- 2 duplicates: #448 (of #444), #336 (of chimney#1)
- 2 stale: #323, #196
- 1 moot: #461, #463

## Prevention

- A single corrective signal cannot override compounding LLM priors — fix all reinforcing signals simultaneously.
- `needs-human` issues need lifecycle management, not just creation.
- Fuzzy dedup must account for verb synonyms in issue titles.
- Cross-repo awareness prevents orphaned issues when repos are split.
- One-shot GitHub Actions events need retry mechanisms for critical workflows.

## Related

- [Observation loop creates bogus issues](./observation-loop-creates-bogus-issues-for-existing-features.md) — the original codebase visibility gap
- [Manually filed issues bypass pipeline triage](./manually-filed-issues-bypass-pipeline-triage.md) — the label gate gap
