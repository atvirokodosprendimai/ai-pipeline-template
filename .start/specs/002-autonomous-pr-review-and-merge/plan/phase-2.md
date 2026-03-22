---
title: "Phase 2: Fix Loop and Retry Orchestration"
status: pending
version: "1.0"
phase: 2
---

# Phase 2: Fix Loop and Retry Orchestration

## Phase Context

**GATE**: Read all referenced files before starting this phase.

**Specification References**:
- `[ref: SDD/Runtime View/Secondary Flow: Fix Loop]` — retry sequence diagram
- `[ref: SDD/Implementation Examples/Poll-Review-Merge Core Loop]` — retry while loop
- `[ref: SDD/Integration Points]` — copilot-swe-agent re-assignment API
- `[ref: PRD/Detailed Feature Specifications/Automated Fix Loop]` — business rules and edge cases

**Key Decisions**:
- ADR-3: Ephemeral state — retry counter is a local variable within the script
- ADR-5: Never merge without review — timeouts during retries also escalate
- Fix loop business rules: cumulative feedback, per-PR retry limit, manual push resets counter

**Dependencies**:
- Phase 1 complete (core script with poll, guardrails, merge, escalate functions)
- Requires: `copilot-swe-agent[bot]` assignment API available on target repo
- Requires: API version header `X-GitHub-Api-Version: 2022-11-28`

---

## Tasks

Adds the fix loop capability: when Copilot review has comments, re-assign the coding agent with feedback, wait for fixes, and re-evaluate. Up to 3 retries before escalation.

- [ ] **T2.1 Agent re-assignment with review feedback** `[activity: backend-scripting]`

  1. Prime: Read `approve-build.yml` lines 107-126 for existing assignment pattern. Read SDD/Integration Points for copilot-swe-agent API contract. Read `docs/interfaces/github-api-pipeline.md`. `[ref: SDD/Interface Specifications/Integration Points]`
  2. Test: `reassign_agent()` collects all inline comments from current review; constructs cumulative feedback string (all reviews, not just latest); calls assignment API with correct headers (`X-GitHub-Api-Version: 2022-11-28`); passes review feedback as `agent_assignment.custom_instructions`; logs `pr_retry_attempted` to audit with attempt number and comment summary
  3. Implement: Add `collect_review_feedback()` to extract comments from `/pulls/{pr}/comments` endpoint. Add `reassign_agent()` to POST to `/issues/{pr}/assignees` with `copilot-swe-agent[bot]` and custom instructions. Handle API errors per Andon (annotation + counter + audit).
  4. Validate: API call uses correct endpoint, headers, and body format; feedback is cumulative across retries
  5. Success: Agent re-assigned with feedback `[ref: PRD/AC-2.1]`; cumulative feedback from all reviews `[ref: PRD/Detailed Feature Specs/Rule 1]`; retry logged `[ref: PRD/AC-2.4]`

- [ ] **T2.2 Retry loop orchestration** `[activity: backend-scripting]`

  1. Prime: Read SDD/Runtime View/Secondary Flow sequence diagram. Read PRD/Detailed Feature Specifications/Business Rules (all 5 rules). `[ref: SDD/Implementation Examples/Poll-Review-Merge Core Loop; lines: retry while loop]`
  2. Test: When comments found and retry_count < MAX_RETRY_COUNT: re-assigns agent, polls for new review, re-checks comments; when comments found and retry_count >= MAX_RETRY_COUNT: escalates with "retries exhausted" and full review history; when review times out during retry: escalates with "review timeout during retry N"; retry counter increments correctly; MAX_RETRY_COUNT is configurable via env var (default 3)
  3. Implement: Wire the retry while loop into the main flow between review detection and guardrails. The loop: check comments -> if zero, break to guardrails -> if non-zero and retries left, reassign + poll -> if non-zero and no retries, escalate. Pass accumulated feedback across iterations.
  4. Validate: Full flow works: poll -> comments found -> retry -> clean review -> guardrails -> merge; retry exhaustion produces correct escalation with full history
  5. Success: Fix loop retries up to MAX_RETRY_COUNT `[ref: PRD/AC-3.1, AC-3.3]`; feedback is cumulative `[ref: PRD/AC-3.1]`; exhaustion escalates with history `[ref: PRD/AC-3.3]`

- [ ] **T2.3 Manual push detection** `[activity: backend-scripting]`

  1. Prime: Read PRD/Detailed Feature Specifications/Business Rule 3 (non-bot push resets counter). Read PRD/Edge Cases/PR Manually Updated. `[ref: PRD/AC-3.4]`
  2. Test: When a non-bot commit is detected during retry wait (author not in APPROVED_AUTHORS), retry counter resets to 0; logs "manual update detected, resetting retry counter"; normal bot commits do not reset counter
  3. Implement: After polling detects new push, check latest commit author. If author not in APPROVED_AUTHORS, reset retry_count to 0 and log. Use `gh pr view --json commits` or `gh api /pulls/{pr}/commits` to check latest commit author.
  4. Validate: Manual push resets counter; bot push does not; edge case of mixed commits handled
  5. Success: Manual intervention resets fix loop `[ref: PRD/AC-3.4]`

- [ ] **T2.4 Phase 2 Validation** `[activity: validate]`

  - Run `shellcheck` on updated script. Trace the complete fix loop flow: review with comments -> reassign -> new review clean -> guardrails -> merge. Trace exhaustion flow: 3 retries -> all have comments -> escalate with full history. Verify all audit log entries for retry events are valid JSONL.
  - Success:
    - [ ] Script passes `shellcheck` with zero warnings `[ref: SDD/Quality Requirements/Testability]`
    - [ ] Fix loop produces correct `pr_retry_attempted` entries `[ref: PRD/AC-2.4]`
    - [ ] Exhaustion produces `pr_escalated` with retry history `[ref: PRD/AC-3.3]`
    - [ ] Manual push resets counter `[ref: PRD/AC-3.4]`
    - [ ] All Phase 1 tests still pass (no regressions)
