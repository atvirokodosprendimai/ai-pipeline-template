---
title: "Manually filed issues bypass pipeline triage — no spec generated"
category: logic-errors
date: 2026-03-18
tags: [copilot-triage, pipeline, labels, needs-triage, manual-issues]
related_issues:
  - https://github.com/atvirokodosprendimai/wgmesh/issues/457
severity: high
component: copilot-triage
---

# Manually filed issues bypass pipeline triage — no spec generated

## Problem

Issue wgmesh#457 (NAT relay flapping) was filed on 2026-03-16 and identified as the top blocker in three consecutive observation loop assessments. Despite this, no spec PR was ever created and no Copilot agent was assigned. The pipeline silently ignored the issue for 2+ days.

## Root Cause

The `copilot-triage.yml` workflow had a single entry point: the `needs-triage` label.

```yaml
if: github.event.label.name == 'needs-triage'
```

Issue #457 was filed manually (from beta tester chat logs) with only the `bug` label. The observation loop creates issues with `fn:dev` + `needs-triage`, but it correctly did not re-create #457 since it already existed. It also had no mechanism to relabel existing issues — its output schema supports `issues_to_create` and `issues_to_close`, but not `issues_to_relabel`.

The triage workflow fired when the `bug` label was applied, evaluated the `if` condition as false, and skipped. No error, no warning, no trace — the issue simply fell through.

## Solution

Widened the triage trigger to accept multiple pipeline-entry labels:

```yaml
if: >-
  contains(fromJSON('["needs-triage","fn:dev","bug"]'), github.event.label.name) &&
  !contains(join(github.event.issue.labels.*.name, ','), 'copilot-triaging')
```

Changes:
1. **Multiple entry labels**: `needs-triage` (loop-created), `fn:dev` (dev work), `bug` (manual reports) all trigger triage.
2. **Double-assignment guard**: Skips if issue already has `copilot-triaging` label. Prevents re-triggering when multiple labels are added to the same issue.
3. **Selective label cleanup**: Only removes `needs-triage` (the pipeline-specific label); preserves `bug` and `fn:dev` which carry semantic meaning.

## Investigation Steps

1. Traced pipeline flow: issue → `needs-triage` label → `copilot-triage.yml` → Copilot spec → validation → approval → Goose build
2. Checked issue #457 state: labels `[bug]`, assignees `[]`, comments `[]` — completely untouched by pipeline
3. Checked triage workflow runs: fired on 2026-03-16 for #457 but conclusion was `skipped` — `if` condition didn't match
4. Compared label on issue (`bug`) vs trigger condition (`needs-triage`) — mismatch confirmed
5. Checked observation loop output schema — has `issues_to_create` and `issues_to_close` but no relabel capability
6. Verified loop assessments referenced #457 as top blocker for 3 consecutive runs without acting on it

## Prevention

- Any new label that should enter the pipeline must be added to the `fromJSON` array in `copilot-triage.yml:17`.
- The `copilot-triaging` guard ensures idempotency regardless of how many triggering labels an issue has.
- Consider adding `issues_to_relabel` to the observation loop output schema so it can push existing issues into the pipeline.
- When filing issues manually, always add `needs-triage` to ensure pipeline pickup.

## Related

- [Observation loop creates bogus issues for existing features](./observation-loop-creates-bogus-issues-for-existing-features.md) — same pipeline, different gap (loop created wrong issues; here it couldn't push existing issues into triage)
- PR [#38](https://github.com/atvirokodosprendimai/ai-pipeline-template/pull/38) — the fix
- `memory/episodic/20260316-0937-claude-nat-relay-issue-filed.md` — session that filed #457 manually
