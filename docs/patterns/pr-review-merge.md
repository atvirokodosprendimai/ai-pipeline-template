# Autonomous PR Review and Merge Pattern

> **Category:** Technical Pattern
> **Last Updated:** 2026-03-22
> **Status:** Active

## Problem

Bot-authored PRs (from Copilot SWE agent, Goose, etc.) sit waiting for human
review, creating a bottleneck in the autonomous development pipeline. Copilot
Code Review can review these PRs automatically, but GitHub App reviews do not
trigger `pull_request_review` workflow events — so a separate merge workflow
never fires.

## Solution

An inline review-merge script (`company/scripts/pr-review-merge.sh`) that runs
as a step within the PR-creating workflow. After the workflow creates a PR, it
immediately invokes the script to poll for Copilot review, enforce guardrails,
and merge — or escalate to a human.

This eliminates queue delay (the script runs in the same job that created the
PR) and avoids the GitHub App event trigger limitation entirely.

## How It Works

```
PR Created → Check manual-only label → Poll for Copilot Review
  → Review arrives → Check inline comments
    → Zero comments → Run guardrails → Merge (squash + delete branch)
    → Has comments → Re-assign agent → Poll again (up to 3 retries)
  → Review timeout → Escalate to human
  → Guardrail fails → Escalate to human
  → Merge fails → Retry once, then escalate
```

## Configuration

All thresholds are configurable via environment variables with sensible defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `PR_MAX_LINES` | `500` | Maximum lines changed before escalation |
| `MAX_RETRY_COUNT` | `3` | Maximum fix-loop retries before escalation |
| `APPROVED_AUTHORS` | `copilot-swe-agent[bot],goose[bot]` | Comma-separated list of allowed PR authors |
| `POLL_INTERVAL` | `30` | Seconds between review polls |
| `POLL_MAX_ATTEMPTS` | `6` | Poll attempts per window |
| `REVIEW_WINDOWS` | `2` | Number of poll windows before timeout |
| `PROTECTED_PATHS` | `.github/,company/scripts/` | Path prefixes that block auto-merge |
| `SECURITY_KEYWORDS` | `secret,token,key,password,api_key,private_key` | Keywords that block auto-merge if found in diff |

Required environment variables (fail-fast if missing):
- `PR_NUMBER` — the PR to process
- `TARGET_REPO` — owner/repo format (per ARCH-5)
- `GH_TOKEN` — authentication token (PUSH_TOKEN, per ARCH-8)

## Guardrails

Evaluated in order, cheapest first. Short-circuits on first failure.

| # | Check | Threshold | On Failure |
|---|-------|-----------|------------|
| 1 | Author allowlist | Must be in `APPROVED_AUTHORS` | Escalate: "Unknown author" |
| 2 | Protected paths | No files under `PROTECTED_PATHS` prefixes | Escalate: "Changes to protected path" |
| 3 | PR size | `additions + deletions <= PR_MAX_LINES` | Escalate: "PR exceeds size limit" |
| 4 | Security keywords | No keywords in added diff lines | Escalate: "Security keyword detected" |
| 5 | CI status | Zero failed check runs | Escalate: "CI checks failed" |

## Escalation Paths

Every escalation adds the `needs-human` label and posts a comment with the reason.

| Reason | When |
|--------|------|
| Copilot review timeout | No review after all poll windows exhausted |
| Review timeout during retry | No review during fix-loop iteration |
| Retries exhausted | Inline comments remain after `MAX_RETRY_COUNT` attempts |
| Unknown author | PR author not in `APPROVED_AUTHORS` |
| Changes to protected path | Files under `.github/` or `company/scripts/` modified |
| PR exceeds size limit | Lines changed exceeds `PR_MAX_LINES` |
| Security keyword detected | Sensitive keyword found in added diff lines |
| CI checks failed | One or more check runs report failure |
| Merge failed after retry | Squash merge failed twice (possible conflict) |

## Fix Loop

When Copilot review has inline comments:

1. Increment retry counter
2. Re-assign `copilot-swe-agent[bot]` with accumulated review feedback
   (via `/issues/{pr}/assignees` with `agent_assignment.custom_instructions`)
3. Poll for new review (same window configuration)
4. Check for manual push — if a human pushed a commit, reset retry counter
5. Re-check inline comments
6. Repeat until clean review or retries exhausted

The manual push detection (AC-3.4) prevents a human fix from being penalised
by the bot's retry counter.

## Integration Example

Add to any PR-creating workflow after the `gh pr create` step:

```yaml
- name: Review and merge PR
  env:
    GH_TOKEN: ${{ secrets.PUSH_TOKEN }}
    TARGET_REPO: ${{ github.repository }}
    PR_NUMBER: ${{ steps.create-pr.outputs.pr_number }}
    # Optional overrides
    PR_MAX_LINES: "500"
    MAX_RETRY_COUNT: "3"
  run: bash company/scripts/pr-review-merge.sh
```

The script exits 0 on both successful merge and successful escalation.
Exit 1 indicates a fatal error (circuit breaker or script failure).

## Constitution Compliance

| Rule | How Satisfied |
|------|---------------|
| **Andon** (Foundational) | Every failure produces `::warning::` or `::error::` + error counter + audit entry. No silent failures. |
| **QUAL-1** (Bash strict mode) | `set -euo pipefail` at script top |
| **QUAL-5** (No silent errors) | All `2>/dev/null` usage paired with error handlers. No bare `\|\| true`. |
| **QUAL-6** (JSON via jq) | All JSON constructed with `jq -nc --arg`. No string interpolation. |
| **QUAL-7** (Manual-only check) | `check_manual_only()` checks label before any automation |
| **SEC-2** (Sanitise published content) | All PR comments/labels pass through `sanitise.sh` |
| **SEC-7** (Circuit breaker) | `check_circuit_breaker()` halts at 5 errors |
| **ARCH-2** (Scripts in company/scripts/) | Script lives at `company/scripts/pr-review-merge.sh` |
| **ARCH-4** (Auto-merge scoped to data paths) | Protected paths guardrail blocks `.github/` and `company/scripts/` changes |
| **ARCH-5** (Cross-repo via TARGET_REPO) | All operations use `TARGET_REPO` env var |

## Related Documentation

- [Workflow Self-Merge Pattern](workflow-self-merge.md) — the simpler pattern for machine-generated data PRs
- `company/scripts/pr-review-merge.sh` — the implementation
- `.start/specs/002-autonomous-pr-review-and-merge/` — full specification
- `CONSTITUTION.md` — enforceable rules this pattern complies with

## Version History

| Date | Change |
|------|--------|
| 2026-03-22 | Initial pattern document |
