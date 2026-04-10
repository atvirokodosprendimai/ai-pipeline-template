---
date: 2026-03-18T23:35:00Z
agent: claude
type: session
tags: [rca, pipeline, copilot-triage, labels, wgmesh-457]
status: resolved
outcome: success
---

## Summary

RCA of why wgmesh#457 (NAT relay flapping) was not being processed by the AI pipeline despite being identified as the top blocker in 3 consecutive observation loop assessments.

## Root Cause

`copilot-triage.yml` only triggered on `needs-triage` label. Issue #457 was filed manually with only the `bug` label. The observation loop couldn't relabel existing issues — its schema supports `issues_to_create` and `issues_to_close` but not `issues_to_relabel`.

## Investigation

1. Traced full pipeline flow: issue -> `needs-triage` label -> `copilot-triage.yml` -> Copilot writes spec -> validation -> approval -> Goose implements
2. Checked #457 state: labels `[bug]`, no assignees, no comments — untouched by pipeline
3. Checked triage workflow runs: fired on 2026-03-16 for #457, conclusion `skipped` — `if` condition didn't match
4. Confirmed label mismatch: issue had `bug`, trigger required `needs-triage`
5. Confirmed observation loop has no relabel capability in output schema

## Actions Taken

### Immediate fix
- Added `needs-triage` + `fn:dev` labels to wgmesh#457
- Copilot was assigned and triage workflow completed successfully
- Issue now has `copilot-triaging` label and Copilot assignee

### Systemic fix (PR #38)
- Widened `copilot-triage.yml` trigger to accept `needs-triage`, `fn:dev`, and `bug` labels
- Added `copilot-triaging` guard to prevent double-assignment
- Selective label cleanup: only removes `needs-triage`, preserves `bug` and `fn:dev`

### Documentation
- Created `docs/solutions/logic-errors/manually-filed-issues-bypass-pipeline-triage.md`
- Enriched with investigation steps and cross-references to related RCA

## Key Files Changed

- `.github/workflows/copilot-triage.yml` — widened trigger condition
- `docs/solutions/logic-errors/manually-filed-issues-bypass-pipeline-triage.md` — RCA doc

## Branch

`fix/widen-triage-trigger` — PR #38: https://github.com/atvirokodosprendimai/ai-pipeline-template/pull/38
