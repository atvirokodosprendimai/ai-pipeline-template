# Workflow Self-Merge

> **Category:** Technical Pattern
> **Last Updated:** 2026-03-22
> **Status:** Active

## Purpose

Workflows that create PRs should merge their own PRs immediately after
creation, rather than delegating merge responsibility to a separate
review-triggered workflow.

GitHub Apps — including Copilot reviewer — authenticate with a
`GITHUB_TOKEN`. Actions performed with this token **do not trigger
subsequent workflow events**. This is a deliberate GitHub security feature
to prevent infinite workflow loops. As a result, any auto-merge strategy
that relies on a bot review to fire a `pull_request_review` event will
**silently fail**: no error, no log, no indication that the merge
workflow never ran.

## Context

### When to use

- Automated workflows that create PRs containing low-risk, machine-generated
  changes (state files, daily assessments, health-check data).
- The PR content is deterministic or already validated earlier in the same
  workflow run.
- You need a PR audit trail but do not need human review before merge.

### When NOT to use

- PRs that require human review before landing.
- PRs authored by humans through normal development flow.
- Cases where a PAT (Personal Access Token) is intentionally used to trigger
  downstream workflows — a PAT _will_ fire events, but introduces a security
  tradeoff (the token carries a real user's permissions and can trigger
  unbounded workflow chains).

## Implementation

### Overview

1. The workflow creates a branch, commits changes, and opens a PR.
2. Immediately after `gh pr create`, the same job extracts the PR number and
   calls `gh pr merge` with `--squash --admin --delete-branch`.
3. Merge failure is treated as a **soft error** — the workflow warns and
   continues rather than crashing, leaving the PR open for manual
   intervention.

### Key components

| Component | Role |
|-----------|------|
| `gh pr create` | Opens the PR (audit trail) |
| `gh pr merge --squash --admin --delete-branch` | Merges immediately, bypassing branch protection |
| Soft-fail `if !` guard | Keeps the workflow alive on merge failure |
| Error counter increment | Tracks failures in the workflow summary |
| Audit log JSONL entry | Records merge failures for offline analysis |

### Code example — pipeline-health.yml (lines 694-716)

```yaml
pr_url=$(gh pr create \
  --title "heal: pipeline health check $today" \
  --body "Automated state update from pipeline-health workflow." \
  --base main \
  --head "$branch")

pr_number=$(echo "$pr_url" | grep -o '[0-9]*$')
echo "Created PR #${pr_number}"

# Auto-merge immediately — Copilot reviews (GitHub App) don't trigger
# pull_request_review workflows, so we can't rely on loop-automerge.yml.
# The PR exists as an audit trail; merge it now with admin bypass.
echo "Auto-merging PR #${pr_number}..."
if ! gh pr merge "$pr_number" --squash --admin --delete-branch; then
  echo "::error::Auto-merge failed for PR #${pr_number} — state update did not land on main. PR left open for manual merge."
  ERRORS=$((ERRORS + 1))
  AUDIT_LOG="company/audit-log.jsonl"
  RUN_ID="${GITHUB_RUN_ID:-local}"
  jq -nc --arg ts "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg rid "$RUN_ID" \
    --arg pr "$pr_number" \
    '{timestamp:$ts, run_id:$rid, action:"merge_failed", issue_number:null, target_repo:"self", reason:("PR #" + $pr + " auto-merge failed"), outcome:"error", retry_count:null}' \
    >> "$AUDIT_LOG"
fi
```

### Code example — observation-loop.yml (lines 385-399)

Same pattern, lighter error handling (no counter or audit log):

```yaml
pr_url=$(gh pr create \
  --title "loop: daily assessment $today" \
  --body "Automated assessment from observation loop." \
  --base main \
  --head "$branch")

pr_number=$(echo "$pr_url" | grep -o '[0-9]*$')
echo "Created PR #${pr_number}"

# Self-merge immediately — GitHub Apps (Copilot reviewer) don't trigger
# pull_request_review workflows, so loop-automerge.yml never fires.
echo "Auto-merging PR #${pr_number}..."
if ! gh pr merge "$pr_number" --squash --admin --delete-branch; then
  echo "::error::Auto-merge failed for PR #${pr_number} — assessment data did not land on main. PR left open for manual merge."
fi
```

## Edge Cases and Gotchas

1. **`--admin` requires admin-level token permissions.** The `GITHUB_TOKEN`
   must have write access to contents and pull-requests, and the repository
   settings must allow admin merge bypass. Without this the merge will fail
   silently against branch protection rules.

2. **Race condition with status checks.** If required status checks are
   configured on the branch, `--admin` bypasses them. This is intentional
   for machine-generated PRs but could mask a broken CI configuration if
   applied to human PRs.

3. **Merge conflicts.** If `main` moved between branch push and merge
   attempt, the squash merge can fail. The soft-fail guard ensures the
   workflow does not crash; the PR remains open for manual resolution.

4. **PR still exists after merge.** The closed PR serves as a permanent
   audit record — who created it, what changed, when it merged. Do not
   delete these PRs.

5. **PAT vs GITHUB_TOKEN.** A PAT _would_ trigger `pull_request_review`
   events, making the separate merge workflow viable. However, PATs carry a
   real user's identity and permissions, can trigger unbounded workflow
   chains, and require manual rotation — making self-merge with
   `GITHUB_TOKEN` the safer choice.

## Anti-Patterns

### Review-triggered merge workflow (loop-automerge.yml)

`loop-automerge.yml` listens for `pull_request_review` events on `loop/*`
and `pipeline-health/*` branches and merges when no blocking reviews exist.
This design is correct in theory but **has zero successful runs in its
entire history** because the reviews that land on these PRs come from
GitHub Apps (Copilot reviewer), whose actions never fire
`pull_request_review` events.

The failure mode is completely silent: no workflow run appears, no error is
logged, and the PR sits open indefinitely. This is the exact scenario the
self-merge pattern eliminates.

```yaml
# loop-automerge.yml — BROKEN, kept for reference
on:
  pull_request_review:
    types: [submitted]
    # GitHub Apps (GITHUB_TOKEN) never trigger this event.
    # This workflow has ZERO successful runs.
```

### Polling-based merge

An alternative anti-pattern is a scheduled workflow that polls for
mergeable PRs. This introduces timing races, unnecessary API usage, and
adds latency between PR creation and merge. Self-merge is immediate and
deterministic.

## Related Documentation

- [GitHub docs: Events that trigger workflows](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#triggering-a-workflow-from-a-workflow) — explains why `GITHUB_TOKEN` actions do not trigger further events.
- `.github/workflows/pipeline-health.yml` — primary self-merge implementation with full error handling.
- `.github/workflows/observation-loop.yml` — secondary self-merge implementation.
- `.github/workflows/loop-automerge.yml` — the broken review-triggered approach (retained as reference).

## Version History

| Date | Change |
|------|--------|
| 2026-03-22 | Initial pattern document |
| 2026-03-17 | Self-merge implemented in pipeline-health.yml and observation-loop.yml |
