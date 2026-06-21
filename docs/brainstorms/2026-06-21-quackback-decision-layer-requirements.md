# Quackback as the Autonomous Pipeline's Decision Layer — Requirements

**Date:** 2026-06-21
**Status:** Requirements (ready for `/ce-plan`)
**Scope:** Deep — product
**Source:** Operator-supplied "Autonomous Build Suggestion Workflow with Quackback" spec, mapped onto the wgmesh autobox pipeline.

---

## Summary

Replace GitHub Issues with a self-hosted **Quackback** board as the autonomous pipeline's decision and audit layer. The Observation Loop stops filing GitHub Issues and instead posts **Build Suggestions** to Quackback. Founders/co-founders vote and an authorized founder flips status to **Accepted for Build** — the only trigger that authorizes the box to spend build effort. The box then runs its existing spec → implement → PR pipeline, and the DeepSeek judge auto-merges as it does today. GitHub is touched only for branch, commits, and PR. Every human decision feeds a learning loop.

**Core principle:** *Quackback decides what to build. GitHub stores the code. The judge decides what merges.*

## Problem

The pipeline was built for unattended convergence: the Observation Loop autonomously files GitHub Issues, the box implements them, and judge-gated auto-merge ships them with no human in the loop. That delivered autonomy but left founders without a single visible surface to **see, prioritize, and authorize** what the autonomous company proposes to build. GitHub Issues are a developer artifact, not a founder decision surface, and they conflate "the agent had an idea" with "we decided to build this." There is also no structured capture of human accept/reject judgments for the box to learn from.

## Goals

- Give founders/co-founders one private board to see every build proposal and authorize work.
- Make human acceptance the gate on **what** gets built (prioritization), without re-adding a human gate at merge.
- Move the work queue off GitHub Issues entirely; GitHub becomes code storage only.
- Capture every decision as a durable, auditable, learnable signal.

## Non-goals

- A human merge gate. Judge-gated auto-merge stays the back-end authority (see Decisions).
- A public/community-facing roadmap or voting (board is internal; community is a future option, not built now).
- GitHub Projects / Linear / Jira integration; weighted voting schemes; auto-deploy.
- Replacing the box's internal execution state machine — Quackback is the decision/audit layer, not the box's runtime store.

## Primary actors

- **Autonomous system (the box)** — proposes Build Suggestions, builds accepted ones, reports progress. Acts via a dedicated named Quackback API key (no human identity).
- **Founders + co-founders** — vote, comment, request refinement, and hold sole `Accepted for Build` authority. Private internal board.

## Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Front gate | Quackback `Accepted for Build` authorizes build | Human prioritization; the only build trigger |
| Back gate (merge) | **Keep DeepSeek judge auto-merge** | Preserves shipped #1919/#1921 work; spec's "human PR review" step is dropped |
| Rollout | **Hard replace day one** | Stop GitHub Issue generation, drain existing issues, Quackback becomes the only queue |
| Authority | Founders + co-founders, private board | Matches co-founder decision model |
| Learning loop | All four mechanisms (below) | Operator: "autonomous learning mode should see scores/evals" |
| Hosting default | Self-host Quackback (Docker/Railway) | AGPL-3.0; aligns with no-component-paywall constitution; control |
| Integration path | MCP server primary, REST fallback | 27-tool MCP server is purpose-built for agents |
| Work discovery | Webhook (`Accepted for Build`) primary, poll fallback | Real-time, HMAC-verified |

## The funnel (status machine)

Quackback statuses, configured via the API:

```
Open for Vote → Needs Refinement → Open for Vote
Open for Vote → Accepted for Build → Building → Ready for Review → Shipped
Open for Vote → Rejected
{Accepted for Build, Building, Ready for Review} → Cancelled
```

- **Open for Vote** — box created a suggestion; founders vote/comment.
- **Needs Refinement** — founder wants more detail; box revises the *same* post (never a duplicate), returns it to Open for Vote.
- **Accepted for Build** — authorized founder approved. The only status the box may act on.
- **Building / Ready for Review / Shipped** — box-driven progress, mirrored from the real pipeline (Ready for Review ↔ PR open; Shipped ↔ judge auto-merge completed).
- **Rejected** (reason required) / **Cancelled** — terminal; box ignores.

The box may set `Building`, `Ready for Review`, `Shipped`. The box may **never** set `Accepted for Build`, `Rejected`, or vote.

## How it maps onto the existing pipeline

- **Observation Loop cron** (today: files GitHub Issues): now creates Build Suggestions in Quackback at `Open for Vote`, using the spec's Build Suggestion template (Summary / Problem / Suggested Build / Why Now / Value / Evidence / Complexity / Risk / Affected Areas / Acceptance Criteria / Non-goals / Alternatives / Open Questions / Stop-Rollback / Agent Confidence / Agent Notes). Required tags `agent-suggestion`, `build-candidate`.
- **Work discovery** splits cleanly. The *issue* side (proposals, decisions, status) lives in Quackback via a new client. The *PR/code* side stays on the existing Forge/GitHub path. The box's stage machine reads `Accepted for Build` posts as its work queue instead of GitHub Issues.
- **Two-layer state.** Quackback = source of truth for decisions + audit. The box keeps its own internal execution-state record keyed by `quackback_post_id` (current stage, branch, PR, agent run id) for idempotency. The two never merge.
- **Bot identity.** A single named, least-privilege Quackback API key. This dissolves the prior `reviewer-PAT` distinct-identity (422) problem — Quackback attributes actions to the key name, no second human account needed.
- **Judge auto-merge** is unchanged. When a PR auto-merges, the box flips the linked post to `Shipped`.

## Decision & acceptance rules

- Votes are **signal only**; they never trigger a build (MVP). An authorized founder's status change to `Accepted for Build` is the contract.
- A suggestion may be accepted when: an authorized founder approves **and** no blocking objection is unresolved **and** the suggestion has enough detail to implement.
- Rejection requires a reason comment. Refinement requires a comment naming what's missing; the box revises the same post.

## Agent execution rule

The box starts implementation only when **all** hold: board = Build Suggestions, status = `Accepted for Build`, tags include `agent-suggestion` + `build-candidate`, and idempotency check passes. On pickup it: verifies the conditions, marks the post `Building`, comments an implementation-start note, and begins. The box ignores every other status.

## Idempotency

Idempotency key = `quackback_post_id + accepted_for_build + status_version`. Stored in the box's execution-state record so the same acceptance never launches two build runs. Minimum record: `quackback_post_id`, `status_version`, `started_at`, `agent_run_id`, `current_state`, `linked_branch`, `linked_pr`.

## Duplicate detection

Before creating a new Build Suggestion the box searches existing posts across **all** statuses (Quackback's AI duplicate detection plus the box's own title/summary/problem/affected-areas comparison). On a match it comments on or revises the existing post rather than creating a duplicate. This replaces today's 5-keyword fuzzy GitHub-issue dedup.

## GitHub touch policy

Allowed: read repo files, create branch, push commits, open/update PR, read CI. Branch name `agent/qb-<post-id>-<short-title>`. Each commit footer `Quackback: <post-url>`. PR body links back to the Quackback post and copies its Acceptance Criteria. **Forbidden:** creating GitHub Issues, Projects, Discussions, or using GitHub labels/milestones as decision state.

## Learning loop (all four mechanisms)

1. **In-context proposal steering** — before proposing, the box reads recent accept/reject history + rejection reasons so it stops re-suggesting rejected shapes and leans toward accepted ones. Prompt-side, no training.
2. **Langfuse scores** — each decision (accept / reject / refine + vote count) becomes a Langfuse score on the proposal's trace, giving a measurable acceptance-rate eval over time. Reuses the existing eval layer; written **after** the decision for measurement (not as an async gate).
3. **Vote-weighted reranking** — among `Accepted for Build` posts, vote totals set build order. Demand drives the queue.
4. **Decision dataset** — every decision persisted as a structured record (foundation for later analysis / eval-set / fine-tuning; not consumed live beyond the above).

## Notifications & SLA (load-bearing, not polish)

The loop was built for unattended convergence; under this design **build throughput is gated by founder attention.** The existing KPI "0 open items aged > 48h" now depends on humans voting, so notification is a first-class requirement, not an add-on:

- Notify the founder channel on: new Build Suggestion, suggestion needs votes, needs refinement, accepted, rejected, build started, ready for review, shipped.
- Surface aging `Open for Vote` posts against the 48h SLA (reuse the pulse open-age KPI, repointed from GitHub Issues to Quackback).
- Notifications are notification-only (Slack/email); they are never a decision surface.

## Failure handling

- **Post creation fails** → log, retry with backoff, do not start building.
- **Status read fails** → stop, do not build, retry later (fail-closed, matches pipeline convention).
- **Accepted-suggestion processing fails before build starts** → leave status unchanged, comment the reason if safe, alert maintainers, do not touch GitHub.
- **Implementation fails after start** → comment reason + suggested next step; do not mark Ready for Review; may move to Needs Refinement / Cancelled.
- All Quackback writes that sit on the convergence path are best-effort with step-level timeouts (per the telemetry-writes lesson), but the **read** of acceptance state is fail-closed.

## Security requirements

Authenticated API access via a dedicated least-privilege named key; webhook HMAC-SHA256 signature + timestamp replay check (reject > 5 min); idempotency; rate limiting; audit logging. The box must be unable to: accept/reject its own suggestions, vote, change decision rules, delete objections, bypass `Accepted for Build`, force a merge, or deploy.

## Success criteria

- Observation Loop creates template-compliant Build Suggestions in Quackback; zero new GitHub Issues created by the pipeline.
- Founders can vote/comment; an authorized founder can accept / reject / request refinement.
- The box builds only after `Accepted for Build`, marks `Building`, runs the existing pipeline, and the judge auto-merges.
- The later PR links back to the Quackback post; on merge the post goes `Shipped`.
- Duplicate implementation starts are prevented.
- Every decision is auditable in Quackback and emitted as a Langfuse score.
- Aging `Open for Vote` posts are visible against the 48h SLA.

## Dependencies & assumptions

- **Quackback** (`github.com/QuackbackIO/quackback`), AGPL-3.0, self-hosted (Docker/Railway) — *default; cloud `app.quackback.io` is the fallback if self-host infra is deferred.* Requires Postgres + a Redis-compatible store (BullMQ).
- REST API (`/api/v1`, `Authorization: Bearer qb_…`), HMAC-signed webhooks, and the 27-tool MCP server are all documented and confirmed. **MCP server is the primary integration path; REST is the fallback.**
- **Unverified:** Quackback custom-fields API. Assumption — encode the spec's metadata (source, proposal_type, risk_level, complexity, agent_confidence, affected_areas) via **tags + structured Markdown body**, not custom fields, until custom fields are confirmed.
- The Forge protocol's GitHub/Gitea-agnostic shape is assumed reusable as the seam for the Quackback work-queue adapter (confirmed agnostic by repo scan; the *issue* side, not PR side, is what moves).
- Hard-replace requires an existing-GitHub-Issue drain step before cutover.

## Outstanding questions (for `/ce-plan`)

1. Self-host deployment target — own VM next to the box, Railway, or co-located? Postgres/Redis provisioning.
2. MCP vs REST in practice — does the box's current langgraph/langchain runtime consume the MCP server cleanly, or is a thin REST client lower-friction for the first slice?
3. Drain strategy for in-flight GitHub Issues at cutover — migrate to Quackback posts, or finish them on the old path and start Quackback clean?
4. Exact Langfuse score schema for decisions (name, datatype, mapping) to fit the existing eval rules.
5. Webhook endpoint hosting — where does the box receive `Accepted for Build` callbacks (the box is a VM, not a public service); poll fallback may be simpler for slice 1.
6. Status-name canonicalization — create the spec's exact status set in Quackback, or map onto Quackback defaults.

## Suggested slicing (rough, for planning)

- **Slice 1** — Quackback self-host stood up; named bot key; statuses + Build Suggestions board created; box can create one template-compliant suggestion (shadow read, no build).
- **Slice 2** — Acceptance discovery (poll first, webhook later) + execution rule + idempotency store; box builds one accepted post end-to-end through existing pipeline → judge merge → `Shipped`.
- **Slice 3** — Observation Loop repointed to Quackback; GitHub Issue generation removed; existing issues drained (hard cutover).
- **Slice 4** — Learning loop: Langfuse scores + in-context steering + vote reranking + decision dataset.
- **Slice 5** — Notifications + 48h SLA repointed to Quackback; duplicate detection hardened.
