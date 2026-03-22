---
title: "Autonomous PR Review and Merge"
status: draft
version: "1.0"
---

# Product Requirements Document

## Validation Checklist

### CRITICAL GATES (Must Pass)

- [x] All required sections are complete
- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Problem statement is specific and measurable
- [x] Every feature has testable acceptance criteria (Gherkin format)
- [x] No contradictions between sections

### QUALITY CHECKS (Should Pass)

- [x] Problem is validated by evidence (not assumptions)
- [x] Context -> Problem -> Solution flow makes sense
- [x] Every persona has at least one user journey
- [x] All MoSCoW categories addressed (Must/Should/Could/Won't)
- [x] Every metric has corresponding tracking events
- [x] No feature redundancy (check for duplicates)
- [x] No technical implementation details included
- [x] A new team member could understand this PRD

---

## Product Overview

### Vision

Every bot-authored pull request merges or escalates within 10 minutes of creation — zero human bottleneck on the happy path, zero unsafe code on any path.

### Problem Statement

The AI pipeline automates issue triage, specification, and code generation, but drops the ball at the final mile: review and merge. Implementation PRs authored by Goose and Copilot sit for days waiting for human review. In a sample of recent PRs, the median time-to-merge for bot-authored PRs exceeds 48 hours despite Copilot already reviewing every PR automatically within 90 seconds. The reviews exist but nobody acts on them.

**Consequences of not solving this:**
- Pipeline throughput is bottlenecked at review (the slowest stage)
- Bot-generated fixes for production issues sit unmerged while the issue persists
- Developer time is wasted on reviewing machine-generated code that Copilot already approved
- The pipeline's value proposition (autonomous issue resolution) is undermined by manual gates

### Value Proposition

Close the automation gap by acting on Copilot reviews automatically. PRs that pass review merge immediately. PRs that need fixes get automatically re-assigned for correction (up to 3 attempts). PRs that exceed guardrails escalate to a human with clear context. The human reviewer only sees the PRs that genuinely need judgment — not the routine ones.

## User Personas

### Primary Persona: Pipeline Operator (DevOps/SRE)

- **Demographics:** Technical staff responsible for pipeline health and throughput. High comfort with GitHub Actions, CI/CD, and automation tooling. Monitors dashboards and responds to alerts.
- **Goals:** Maximize pipeline throughput. Minimize time-to-merge for bot-authored PRs. Catch risky PRs before they merge. Tune guardrails based on observed patterns.
- **Pain Points:** PRs pile up waiting for review. No visibility into why PRs are stuck. Manual review of machine-generated code is tedious and low-value. Current pipeline metrics show a gap between "PR created" and "PR merged."

### Secondary Personas

#### Developer (PR Author)

- **Demographics:** Software engineer who triggers bot-generated PRs (via issue creation or direct assignment to Goose/Copilot). Moderate-to-high GitHub familiarity.
- **Goals:** See fast feedback on generated PRs. Understand why a PR was blocked or escalated. Trust that auto-merged code is safe.
- **Pain Points:** Unclear why a PR hasn't merged yet. No feedback loop when Copilot flags issues. Must manually check PR status.

#### Human Reviewer (Escalation Handler)

- **Demographics:** Senior engineer or team lead who handles PRs that failed autonomous merge. Reviews escalated PRs during periodic review windows (e.g., daily).
- **Goals:** Quickly understand why a PR was escalated. Make an informed approve/reject decision. Batch-process escalated PRs efficiently.
- **Pain Points:** Lacks context on escalation reason. Must dig through PR history to understand what went wrong. No clear signal distinguishing "needs minor fix" from "fundamentally flawed."

## User Journey Maps

### Primary User Journey: Autonomous Merge (Happy Path)

1. **Trigger:** Pipeline operator has configured the autonomous review system. A Goose agent creates an implementation PR for a triaged issue.
2. **Review:** The system waits for Copilot's automated review (typically 30-90 seconds). The review arrives with zero inline comments — clean approval.
3. **Guardrails:** The system checks: PR is under 500 lines, CI is green, author is a known bot, no security keywords in diff, no workflow file changes.
4. **Merge:** All guardrails pass. PR merges automatically via squash merge. Branch is deleted.
5. **Outcome:** Pipeline operator sees the merge in the audit log. Total time from PR creation to merge: under 5 minutes. No human intervention required.

### Secondary User Journeys

#### Fix Loop Journey

1. **Trigger:** Copilot review contains inline comments (e.g., "missing error handling").
2. **Re-assignment:** System extracts review feedback and re-assigns copilot-swe-agent with the feedback as instructions.
3. **Retry:** Copilot pushes fixes. System waits for a new review. If clean, merges. If still has comments, retries (up to 3 total attempts).
4. **Outcome:** Most fixable issues resolve within 1-2 retries. PR merges autonomously. Audit log captures all retry attempts.

#### Escalation Journey

1. **Trigger:** PR fails a guardrail (too large, security keyword, workflow file change) or exhausts 3 fix retries.
2. **Labeling:** System adds `needs-human` label with a comment explaining the specific escalation reason (e.g., "3 retries exhausted — Copilot still flagging: missing type annotations on lines 42, 67").
3. **Batching:** Human reviewer queries `gh pr list --label needs-human` during their review window.
4. **Decision:** Reviewer inspects the PR, reads the escalation context, and either approves (merge happens within 60 seconds) or requests changes.
5. **Outcome:** Escalated PRs get clear, actionable context. Reviewer spends time on judgment calls, not routine approvals.

#### Manual Override Journey

1. **Trigger:** Pipeline operator adds `manual-only` label to a specific PR (or to a repo-wide label policy).
2. **Behavior:** System detects `manual-only` label and skips all automation for that PR. No review polling, no merge attempt, no fix loop.
3. **Outcome:** Human retains full control when needed. Consistent with existing pipeline-health behavior (QUAL-7).

## Feature Requirements

### Must Have Features

#### Feature 1: Automated Review Detection

- **User Story:** As a pipeline operator, I want the system to detect when Copilot has reviewed a bot-authored PR so that I don't need to manually check review status.
- **Acceptance Criteria (Gherkin Format):**
  - [x] Given a bot-authored PR exists, When Copilot submits a review, Then the system detects the review within 30 seconds of its availability
  - [x] Given no review arrives within 3 minutes, When the first poll window expires, Then the system retries for one additional 3-minute window (6 minutes total)
  - [x] Given no review arrives within 6 minutes total, When the retry window also expires, Then the PR is labeled `needs-human` with reason "Copilot review timeout"
  - [x] Given a PR has the `manual-only` label, When the automation runs, Then the PR is skipped entirely (no polling, no merge attempt)

#### Feature 2: Autonomous Merge

- **User Story:** As a pipeline operator, I want bot-authored PRs that pass all guardrails to merge automatically so that I don't bottleneck the pipeline with manual approvals.
- **Acceptance Criteria (Gherkin Format):**
  - [x] Given a PR has a clean Copilot review (zero inline comments), When all guardrails pass (size, CI, author, security, file paths), Then the PR is squash-merged and the branch is deleted
  - [x] Given a PR has CI checks that have not completed, When merge is attempted, Then the merge is blocked until CI completes (with timeout)
  - [x] Given a PR modifies files under `.github/` or `company/scripts/`, When guardrails are evaluated, Then the PR is labeled `needs-human` regardless of review status
  - [x] Given a merge fails due to a conflict, When the merge command returns an error, Then the system retries once after 10 seconds, and if still failing, labels `needs-human` with reason "merge conflict"

#### Feature 3: Automated Fix Loop

- **User Story:** As a developer, I want Copilot review comments to be automatically fed back to the coding agent so that fixable issues resolve without human intervention.
- **Acceptance Criteria (Gherkin Format):**
  - [x] Given a Copilot review has inline comments, When retry count is less than 3, Then the system re-assigns copilot-swe-agent with all accumulated review feedback as instructions
  - [x] Given the coding agent pushes a fix, When a new Copilot review arrives, Then the system evaluates the new review (same guardrail checks)
  - [x] Given the fix loop has run 3 times, When the latest review still has comments, Then the PR is labeled `needs-human` with a summary of all review comments across retries
  - [x] Given the PR is manually updated (non-bot push) during a fix cycle, When the system detects the new commit author, Then the retry counter resets to 0 and the review cycle restarts

#### Feature 4: Guardrail Gate

- **User Story:** As a pipeline operator, I want configurable safety guardrails that prevent risky PRs from auto-merging so that I maintain control over code quality and security.
- **Acceptance Criteria (Gherkin Format):**
  - [x] Given a PR has more than 500 changed lines, When guardrails are evaluated, Then the PR is labeled `needs-human` with reason "PR exceeds size limit (N lines > 500)"
  - [x] Given a PR diff contains security-sensitive keywords (secret, token, key, password, api_key), When guardrails are evaluated, Then the PR is labeled `needs-human` with reason "security keyword detected: [keyword]"
  - [x] Given a PR author is not in the approved bots list, When guardrails are evaluated, Then the PR is labeled `needs-human` with reason "unknown author: [author]"
  - [x] Given a PR modifies workflow files or scripts, When guardrails are evaluated, Then the PR is labeled `needs-human` with reason "changes to protected paths"
  - [x] Given guardrail thresholds are configured via environment variables, When the operator changes a threshold, Then the new threshold takes effect on the next PR without code changes

#### Feature 5: Escalation with Context

- **User Story:** As a human reviewer, I want escalated PRs to clearly explain why they were escalated so that I can make a quick, informed decision.
- **Acceptance Criteria (Gherkin Format):**
  - [x] Given a PR is escalated for any reason, When the `needs-human` label is applied, Then a comment is posted with: escalation reason, retry history (if applicable), and all Copilot review comments
  - [x] Given a human reviewer approves an escalated PR, When the approval is detected, Then the PR merges within 60 seconds
  - [x] Given multiple PRs are escalated, When a reviewer queries `gh pr list --label needs-human`, Then all escalated PRs appear with their escalation reasons visible

### Should Have Features

#### Feature 6: Audit Trail

- **User Story:** As a pipeline operator, I want every autonomous action logged so that I can audit merge decisions and tune the system.
- **Acceptance Criteria (Gherkin Format):**
  - [x] Given any PR action occurs (review detected, merge, retry, escalation, error), When the action completes, Then an entry is appended to the audit log with: timestamp, PR number, action type, outcome, and details
  - [x] Given a circuit breaker trips (too many escalations in one run), When the threshold is reached, Then a single summary entry is logged and remaining PRs in that run are deferred

#### Feature 7: Configurable Thresholds

- **User Story:** As a pipeline operator, I want to adjust guardrail thresholds without changing code so that I can tune the system for different repos and risk profiles.
- **Acceptance Criteria (Gherkin Format):**
  - [x] Given the operator sets `PR_MAX_LINES=300`, When a PR with 400 lines is evaluated, Then it is escalated (threshold respected)
  - [x] Given the operator sets `MAX_RETRY_COUNT=5`, When a PR exhausts 5 retries, Then it escalates (custom limit honored)
  - [x] Given no environment variables are set, When defaults are used, Then the system uses: 500 lines, 3 retries, approved authors = copilot-swe-agent + goose

### Could Have Features

#### Feature 8: Metrics Dashboard Widgets

- **User Story:** As a pipeline operator, I want dashboard widgets showing auto-merge rate and escalation breakdown so that I can monitor system health at a glance.
- **Acceptance Criteria (Gherkin Format):**
  - [x] Given the audit log has data, When the dashboard renders, Then it shows: auto-merge rate (%), average time-to-merge, escalation rate by reason

#### Feature 9: Escalation Notifications

- **User Story:** As a human reviewer, I want to be notified when PRs are escalated so that I don't need to poll for work.
- **Acceptance Criteria (Gherkin Format):**
  - [x] Given a PR is escalated, When the `needs-human` label is applied, Then a notification is sent (mechanism TBD: GitHub notification, Slack, or issue creation)

### Won't Have (This Phase)

- **Human-authored PR review:** Different trust model; requires consent-based opt-in. Deferred to future work.
- **Cross-repo review coordination:** PRs in one repo depending on changes in another. Too complex for Phase 1.
- **Review quality scoring:** Rating Copilot's review accuracy over time. Requires baseline data collection first.
- **Automatic PR creation:** This system handles PRs after creation. PR creation is handled by existing Goose/Copilot workflows.
- **Duration estimates for fix cycles:** How long Copilot takes to fix varies too much. Not predictable enough to promise.

## Detailed Feature Specifications

### Feature: Automated Fix Loop (Most Complex)

**Description:** When Copilot's review contains inline comments, the system extracts the feedback and re-assigns the coding agent (copilot-swe-agent) with the accumulated review comments as instructions. The agent pushes fixes, a new review is triggered, and the cycle repeats up to 3 times. If the review is clean after any retry, the PR merges normally. If all retries are exhausted, the PR escalates to a human.

**User Flow:**
1. Copilot review arrives with inline comments (e.g., "missing error handling on line 42")
2. System checks retry counter (current attempt < max retries)
3. System collects ALL review comments from ALL previous reviews (cumulative)
4. System re-assigns copilot-swe-agent with the original issue context + accumulated feedback
5. Coding agent pushes a new commit with fixes
6. System waits for a new Copilot review (same polling logic: 3 min + 3 min retry)
7. If new review is clean -> merge. If still has comments -> loop to step 2

**Business Rules:**
- Rule 1: Review feedback is cumulative — each retry includes ALL comments from ALL previous reviews, not just the latest
- Rule 2: Retry counter is per-PR, not per-run — survives across workflow executions
- Rule 3: If a non-bot user pushes to the PR during a fix cycle, the retry counter resets to 0 (human intervention = fresh start)
- Rule 4: Each retry attempt is logged to the audit trail with: attempt number, review comments received, and outcome
- Rule 5: The fix loop never runs on PRs that fail non-code guardrails (size, security, file paths) — those escalate immediately

**Edge Cases:**
- Scenario 1: Fix introduces new issues not in original review -> Expected: New comments are added to cumulative feedback, retry counter increments, loop continues
- Scenario 2: Copilot review times out during retry -> Expected: Retry the review poll once (6 min total), then escalate with reason "review timeout during retry N"
- Scenario 3: Coding agent doesn't push any commits after re-assignment -> Expected: After waiting for push (configurable timeout), escalate with reason "no fix pushed after re-assignment"
- Scenario 4: PR is closed or deleted during fix cycle -> Expected: Detect closed state, log "PR closed externally," stop processing
- Scenario 5: Concurrent fix: two workflows try to re-assign the same PR -> Expected: Concurrency group prevents this; only one workflow per PR branch

## Success Metrics

### Key Performance Indicators

- **Adoption:** 100% of bot-authored PRs in target repo are processed by the autonomous system within 1 month of launch
- **Engagement:** Auto-merge rate > 80% of bot-authored PRs (merge without human intervention)
- **Quality:** False escalation rate < 5% (PRs escalated that a human approves without any changes)
- **Business Impact:** Median time-to-merge for bot-authored PRs drops from 48+ hours to under 10 minutes

### Tracking Requirements

| Event | Properties | Purpose |
|-------|------------|---------|
| pr_review_detected | pr_number, review_time_seconds, comment_count | Measure Copilot review latency and quality |
| pr_auto_merged | pr_number, time_to_merge_seconds, retry_count | Track auto-merge rate and speed |
| pr_retry_attempted | pr_number, attempt_number, comment_summary | Understand fix loop effectiveness |
| pr_escalated | pr_number, reason, retry_count, time_in_system | Identify top escalation causes |
| pr_human_merged | pr_number, time_to_human_action, changes_made | Measure false escalation rate |
| guardrail_triggered | pr_number, guardrail_name, details | Track which guardrails fire most |
| circuit_breaker_tripped | run_id, escalation_count, prs_deferred | Monitor system health |
| review_timeout | pr_number, poll_duration_seconds, retry_attempted | Track Copilot availability |

---

## Constraints and Assumptions

### Constraints

- **GitHub Actions execution:** All automation runs within GitHub Actions workflows. Subject to runner availability, billing limits, and execution time caps.
- **Copilot review SLA:** No guaranteed latency for Copilot reviews. Typical range is 30-90 seconds, but can exceed 2 minutes under load.
- **Branch protection:** Auto-merge requires `--admin` flag to bypass branch protection rules. This is acceptable for bot-authored PRs with guardrails.
- **Token permissions:** All operations require a Personal Access Token (PUSH_TOKEN) with contents:write, pull-requests:write, and issues:write scopes.
- **Constitution compliance:** All behavior must comply with CONSTITUTION.md rules, particularly: Andon principle (no silent failures), SEC-1 through SEC-7, ARCH-4 (data path scoping), and QUAL-7 (manual-only label).

### Assumptions

- **Copilot reviews are available:** Copilot code review is enabled on the target repository and reviews bot-authored PRs automatically.
- **Bot authors are identifiable:** PR author metadata reliably identifies bot accounts (copilot-swe-agent[bot], goose).
- **CI runs on bot PRs:** CI pipelines trigger on bot-authored PRs the same as human PRs.
- **Single-repo scope (Phase 1):** Phase 1 targets a single repository (wgmesh). Multi-repo support is Phase 3.
- **Copilot-swe-agent accepts re-assignment:** The coding agent can be re-assigned via the GitHub API with custom instructions containing review feedback.

## Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Copilot merges unsafe code that review missed | High | Low | Guardrails (size, security keywords, file paths) catch categories Copilot might miss. Audit trail enables post-mortem. |
| Bot account compromised, pushes malicious PR | High | Very Low | Author allowlist + file path restrictions + security keyword scanning. Workflow files always require human review. |
| Fix loop creates infinite retry cycles | Medium | Low | Hard cap at 3 retries per PR. Circuit breaker caps escalations per run. |
| Copilot review unavailable (outage) | Medium | Low | 6-minute timeout (3 min + 3 min retry) then escalate. Never merge without review. |
| Race condition: PR modified between review and merge | Medium | Low | Re-check PR state immediately before merge command. Concurrency group prevents parallel merge attempts. |
| False escalations frustrate developers | Low | Medium | Clear escalation reasons in PR comments. Configurable thresholds. Track false escalation rate as KPI. |
| GitHub Actions billing spike from polling loops | Low | Medium | Inline (event-driven) design minimizes polling. Budget monitoring. Phase 2+ may need paid tier ($0.25/month estimated). |

## Open Questions

- [ ] Should escalated PRs also create a tracking issue, or is the `needs-human` label + PR comment sufficient?
- [ ] What notification channel should be used for escalations? (GitHub notification, Slack webhook, or both?)
- [ ] Should auto-closed escalation issues be created when a human merges an escalated PR?
- [ ] Should escalation metrics feed back into Goose's spec generation to prevent recurring issues?

---

## Supporting Research

### Competitive Analysis

No direct competitors for "autonomous PR merge with AI review" in the GitHub Actions ecosystem. Adjacent approaches:
- **Mergify:** Rule-based auto-merge (no AI review component, no fix loop)
- **Kodiak:** Auto-merge on approval (requires human approval, no autonomous review)
- **GitHub auto-merge:** Native feature, but requires human-initiated approval and passing checks

This system is differentiated by the **AI review + fix loop + guardrail** combination — it doesn't just auto-merge on rules, it acts on AI judgment with safety nets.

### User Research

Evidence from project history:
- PR wgmesh#464 sat for 3+ days with a clean Copilot review — zero human action needed, but nobody acted on the review
- Pipeline-health self-merge pattern (data PRs) has been running successfully for weeks with zero incidents
- The existing Andon-based circuit breaker has prevented runaway automation in healing loops

### Market Data

- GitHub reports 100M+ developers on the platform. Copilot code review is expanding to all GitHub Enterprise users.
- The trend toward AI-assisted development creates a growing volume of bot-authored PRs that need automated merge workflows.
- Queue theory research validates inline (push) processing over polling (pull) for latency-sensitive pipelines. A 5-stage pipeline with 15-minute polling at each stage adds 75 minutes of pure wait time.
