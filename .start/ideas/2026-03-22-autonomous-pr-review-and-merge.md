# Autonomous PR Review and Merge

> Date: 2026-03-22
> Status: Approved for specification

## Problem

The pipeline automates issue -> triage -> spec -> build but drops the ball at review and merge. Implementation PRs (like wgmesh#464) sit for days with nobody acting on them. The pipeline self-heals stuck *issues* but not stuck *PRs*.

## Design Decisions

- **Trust level:** Auto review + merge with guardrails. PRs that meet strict criteria merge autonomously; risky PRs escalate to human.
- **Reviewer:** Copilot (paid, strong model). Already reviews every PR automatically. The missing piece is acting on the reviews.
- **Trigger:** Inline at point of PR creation (queue theory: process at creation, don't batch into polling queues). Same pattern as pipeline-health self-merge.
- **Fix loop:** Re-assign copilot-swe-agent with review feedback as instructions. Fully autonomous retry (max 3 attempts before needs-human).

## Flow

```
PR created (by Goose/Copilot)
  -> Wait for Copilot review (poll 30s x 6)
  -> Check guardrails (size, tests, author)
  |
  +- Clean review + guardrails pass -> MERGE
  |
  +- Comments found + retries < 3
  |    -> Re-assign copilot-swe-agent with review feedback
  |    -> Wait for push + new review
  |    -> Loop back to check
  |
  +- Comments found + retries >= 3 -> label needs-human
  |
  +- Guardrails fail (>500 lines, security flag) -> label needs-human
```

## Guardrails

| Check | Threshold | On fail |
|-------|-----------|---------|
| PR size | <= 500 changed lines | needs-human |
| Tests | Must pass (CI green) | Block merge, retry |
| Author | Known bots only (copilot-swe-agent, goose) | needs-human for unknown authors |
| Review comments | Zero inline after fixes | Loop (max 3 retries) |
| Security keywords | No secret, token, key in diff | needs-human |

## Architecture

- Lives inline in the workflow that creates the PR (goose-build.yml equivalent)
- No separate merge workflow, no polling queue
- Each workflow owns its PR's full lifecycle
- Andon compliant: every failure counted, logged, escalated after threshold

## Queue Theory Rationale

Push (inline) beats pull (polling) for latency. A 5-stage pipeline with 15-min polling at each stage adds 75 min of pure wait. Inline processing has zero queue delay.

## Scope

- Phase 1: Implementation PRs (Goose-authored) in wgmesh
- Phase 2: Spec PRs (Copilot-authored) in wgmesh
- Phase 3: Any bot-authored PR across all repos

## Parking Lot (deferred)

- Human-authored PR review (different trust model)
- Cross-repo review coordination
- Review quality metrics and feedback loop
