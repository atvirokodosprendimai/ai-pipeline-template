---
title: "Pipeline Self-Healing and Observability"
status: complete
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
- [x] Context → Problem → Solution flow makes sense
- [x] Every persona has at least one user journey
- [x] All MoSCoW categories addressed (Must/Should/Could/Won't)
- [x] Every metric has corresponding tracking events
- [x] No feature redundancy (check for duplicates)
- [x] No technical implementation details included
- [x] A new team member could understand this PRD

---

## Product Overview

### Vision

Make the AI pipeline self-aware and self-correcting so that issues flow from creation to implementation without human babysitting, with a single dashboard showing the entire pipeline state at a glance.

### Problem Statement

The AI pipeline currently relies on an LLM-based observation loop (every 8h) for board hygiene and manual human intervention for stale state detection. Real-world evidence from RCA sessions (2026-03-16 through 2026-03-18) proved that LLMs are unreliable for mechanical tasks — they missed reconciliation signals, ignored compounding indicators, and created duplicate issues for features that already existed. Meanwhile, issues get stuck at pipeline stages for 24-48+ hours without detection because:

1. **No dedicated health monitoring** — the observation loop runs every 8h, so a stuck issue waits up to 8h for detection (plus resolution time).
2. **No visibility** — the founder must manually check GitHub labels across repositories to understand pipeline state. There is no single view showing bottlenecks.
3. **No automated recovery** — when Copilot triage fails silently or Goose build times out, recovery requires manual label toggling and workflow re-triggering.

The consequence: a solo founder spends 30+ minutes per day on pipeline housekeeping that should be zero.

### Value Proposition

Deterministic self-healing (code, not prompts) running every 2h catches stuck issues 4x faster than the current 8h loop. A pipeline dashboard at chimney.beerpub.dev/pipeline provides instant visibility without touching GitHub. Together, they reduce founder pipeline overhead from 30+ min/day to a 30-second dashboard glance, while improving issue throughput by eliminating multi-hour stalls.

## User Personas

### Primary Persona: Solo Founder (Pipeline Operator)

- **Demographics:** Technical founder, mid-30s, runs the entire company solo. High technical expertise. Uses GitHub daily, checks chimney dashboard on mobile and desktop.
- **Goals:** Operate an autonomous AI pipeline that turns issues into merged PRs with zero manual intervention. See at a glance whether the pipeline is healthy. Focus time on product decisions, not pipeline plumbing.
- **Pain Points:** Spends 30+ min/day manually checking GitHub for stale issues. Misses stuck states for hours because there's no alerting. Has to remember which labels to toggle and which workflows to re-trigger. Cannot tell from a phone whether the pipeline is working.

### Secondary Persona: Observation Loop (Automated System)

- **Demographics:** LLM-based workflow running every 8h. Consumes state files and GitHub signals. Makes assessment decisions.
- **Goals:** Have accurate, up-to-date pipeline health data to inform assessments. Avoid creating duplicate issues for problems that self-healing already resolved.
- **Pain Points:** Cannot detect stale issues between 8h runs. Has no structured health signal to consume. Sometimes creates duplicate needs-human issues for problems that were already auto-resolved.

## User Journey Maps

### Primary User Journey: Founder Reviews Pipeline Health

1. **Awareness:** Founder opens chimney.beerpub.dev/pipeline (bookmarked) after morning coffee or when a self-healing notification appears in the assessment history.
2. **Consideration:** Scans the alert zone — any red (>24h stale) or yellow (approaching threshold) issues? If all green, done in 5 seconds.
3. **Adoption:** First time: founder sees the Kanban layout, understands columns map to pipeline stages, reads the banner showing funnel stage and runway.
4. **Usage:** If issues are flagged, clicks the issue card to open GitHub in a new tab. Reviews the self-healing log ("Last healed: 2h ago, fixed 3 stale issues") to understand what was already auto-resolved.
5. **Retention:** Checks dashboard daily. Trusts self-healing to handle routine stalls. Only intervenes for needs-human escalations (after 2 consecutive failures).

### Secondary User Journey: Self-Healing Resolves a Stale Issue

1. **Detection:** Pipeline health workflow runs (every 2h). Queries GitHub for issues labeled `needs-triage` older than 24h.
2. **Diagnosis:** Finds issue #42 stuck at `needs-triage` for 26h — Copilot triage workflow never fired.
3. **Recovery:** Removes `needs-triage` label, waits 2 seconds, re-applies label. This re-triggers the Copilot triage workflow.
4. **Verification:** On next 2h cycle, checks if issue #42 now has `copilot-triaging` label. If yes, healed. If no, increments failure counter.
5. **Escalation:** After 2 consecutive failures (4h total), creates a `needs-human` issue: "Issue #42 stuck at triage after 2 self-healing attempts."

## Feature Requirements

### Must Have Features

#### Feature 1: Stale Triage Detection and Recovery

- **User Story:** As the pipeline operator, I want issues stuck at `needs-triage` for over 24h to be automatically re-triggered, so that Copilot triage failures don't require manual intervention.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given an issue labeled `needs-triage` for more than 24h, When the self-healing workflow runs, Then the label is removed and re-applied to re-trigger the Copilot triage workflow
  - [ ] Given an issue labeled `needs-triage` that also has `wont-do` or `needs-info`, When the self-healing workflow runs, Then the issue is skipped (already resolved)
  - [ ] Given a re-triggered issue that fails triage again within 4h, When the second self-healing cycle detects it still stuck, Then a `needs-human` issue is created with the failure context

#### Feature 2: Stale Copilot Triaging Recovery

- **User Story:** As the pipeline operator, I want issues stuck at `copilot-triaging` for over 48h to be automatically retried, so that silent Copilot failures are recovered without manual re-assignment.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given an issue labeled `copilot-triaging` for more than 48h with no spec PR opened, When the self-healing workflow runs, Then Copilot is re-assigned to the issue with a retry comment
  - [ ] Given an issue where Copilot has already created a spec PR (in progress), When the self-healing workflow runs, Then the issue is skipped (work in progress)
  - [ ] Given 2 consecutive re-assignment failures, When the self-healing workflow detects the third stall, Then a `needs-human` issue is escalated

#### Feature 3: Stale Build Approval Recovery

- **User Story:** As the pipeline operator, I want spec PRs stuck at `approved-for-build` for over 24h to automatically re-trigger the Goose build, so that silent build failures don't block the pipeline.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given a PR labeled `approved-for-build` for more than 24h with no implementation PR created, When the self-healing workflow runs, Then the Goose build workflow is re-triggered
  - [ ] Given a Goose build that has already been re-triggered and failed, When the second self-healing cycle detects the PR still stuck, Then a `needs-human` issue is created
  - [ ] Given a PR where an implementation PR already exists but is unlabeled, When the self-healing workflow runs, Then the existing PR is detected and no re-trigger occurs

#### Feature 4: Fulfilled Needs-Human Auto-Close

- **User Story:** As the pipeline operator, I want `needs-human` issues that have been resolved (linked PR merged, human comment added, or signals now present) to be automatically closed, so that the board stays clean.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given a `needs-human` issue with a linked merged PR, When the self-healing workflow runs, Then the issue is closed with comment "Resolved: linked PR merged"
  - [ ] Given a `needs-human` issue about a missing API key where the key is now configured (workflow succeeds), When the self-healing workflow runs, Then the issue is closed with the resolution reason
  - [ ] Given a `needs-human` issue with no resolution signals, When the self-healing workflow runs, Then the issue is left open

#### Feature 5: Pipeline Dashboard

- **User Story:** As the pipeline operator, I want a single dashboard showing every issue's position in the pipeline with health indicators, so that I can assess pipeline health in under 10 seconds without opening GitHub.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given the dashboard is loaded, When the page renders, Then issues are grouped into 6 Kanban columns: Created, Triaging, Spec PR, Approved, Implementing, Merged
  - [ ] Given an issue has been in its current stage for more than 24h, When the dashboard renders, Then the issue card displays a red health indicator
  - [ ] Given an issue has been in its current stage for 20-24h, When the dashboard renders, Then the issue card displays a yellow health indicator
  - [ ] Given the dashboard is loaded, When the banner renders, Then it shows the current funnel stage name, runway (months remaining), and last self-healing timestamp
  - [ ] Given the user clicks an issue card, When the click event fires, Then the user is navigated to the GitHub issue page in a new tab
  - [ ] Given the dashboard is accessed on a mobile device, When the page renders, Then columns are displayed as a swipeable carousel with 48px+ touch targets

#### Feature 6: Self-Healing Audit Trail

- **User Story:** As the pipeline operator, I want every self-healing action logged with timestamp, action, and reason, so that I can review what the system did and debug false positives.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given the self-healing workflow completes a run, When any action is taken (label re-applied, issue closed, workflow re-triggered), Then the action is logged with timestamp, action type, issue number, and reason
  - [ ] Given the dashboard is loaded, When the user clicks "Last healed" in the banner, Then a log of recent self-healing actions is displayed
  - [ ] Given no self-healing actions were taken in a cycle, When the workflow completes, Then a "no action needed" entry is logged

#### Feature 7: Circuit Breaker

- **User Story:** As the pipeline operator, I want self-healing to stop retrying after 2 consecutive failures and escalate to me, so that broken workflows don't cause infinite retry loops.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given a self-healing action has failed 2 consecutive times for the same issue, When the third cycle begins, Then no retry is attempted and a `needs-human` issue is created instead
  - [ ] Given more than 10 issues are created or more than 5 actions fail in a single run, When the circuit breaker triggers, Then the workflow stops processing and creates a single escalation issue
  - [ ] Given a circuit breaker has triggered, When the next self-healing cycle runs, Then the breaker resets and normal operation resumes (24h cooldown per issue)

### Should Have Features

#### Feature 8: Self-Healing Activity in Dashboard Banner

- **User Story:** As the pipeline operator, I want the dashboard banner to show "Last healed: Xh ago, fixed N stale issues" so that I know self-healing is active without checking logs.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given self-healing ran 2h ago and fixed 3 issues, When the dashboard banner renders, Then it displays "Last healed: 2h ago, fixed 3 stale issues"
  - [ ] Given self-healing has never run, When the dashboard banner renders, Then it displays "Self-healing: not yet active"

#### Feature 9: Dashboard Empty and Error States

- **User Story:** As the pipeline operator, I want the dashboard to show clear messages when the pipeline is empty, all healthy, or data is stale, so that I'm never confused by blank screens.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given no open issues exist in the pipeline, When the dashboard loads, Then it shows "Pipeline is empty. Create an issue to get started." with a link to the issue template
  - [ ] Given all issues are flowing (none stale), When the dashboard loads, Then it shows a success indicator in the alert zone
  - [ ] Given the dashboard data is more than 4h stale, When the dashboard loads, Then it shows a warning "Data stale. Last sync: Xh ago"

### Could Have Features

#### Feature 10: Funnel Stage Signal Detection

- **User Story:** As the pipeline operator, I want self-healing to detect when funnel advancement signals are present and report them, so that the observation loop can make informed advancement decisions.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given the product repo has a CLAUDE.md with Architecture and Build sections, When self-healing checks funnel signals, Then it reports "Dogfood signals detected" in its state file
  - [ ] Given all health.json endpoints respond with 200, When self-healing checks funnel signals, Then it reports "Presence signals detected"

#### Feature 11: Dashboard Health History

- **User Story:** As the pipeline operator, I want to see a trend of pipeline health over time, so that I can spot systemic degradation.
- **Acceptance Criteria (Gherkin Format):**
  - [ ] Given the dashboard displays history, When 7+ days of data exist, Then a simple bar chart shows issues healed per day

### Won't Have (This Phase)

- **Dashboard editing** — No ability to change labels, close issues, or trigger workflows from the dashboard. The dashboard is read-only; self-healing and GitHub own all mutations.
- **Funnel auto-advancement** — Self-healing detects signals but does NOT advance the funnel stage. The observation loop (LLM) retains that authority.
- **Real-time updates** — Dashboard uses 15-minute cached data from GitHub API, not WebSocket live updates.
- **Authentication** — Dashboard is public. Sensitive data (assessment narratives, blockers, strategy) is not displayed.
- **Multi-repo pipeline view** — Dashboard shows wgmesh pipeline only. Secondary repos are out of scope.
- **Slack/email notifications** — No push notifications for self-healing events. Dashboard + GitHub are sufficient.

## Detailed Feature Specifications

### Feature: Pipeline Dashboard (Most Complex)

**Description:** A Kanban-style web dashboard at chimney.beerpub.dev/pipeline showing every open issue's position in the AI pipeline. Each issue appears as a card in one of 6 columns, color-coded by health. A top banner shows the company funnel stage, financial runway, and last self-healing activity.

**User Flow:**
1. User navigates to chimney.beerpub.dev/pipeline
2. Dashboard loads, fetches issue data from GitHub API (or 15-min cache)
3. Banner displays: funnel stage ("Dogfood"), runway ("48 months"), last healed ("2h ago, fixed 3 issues")
4. Alert zone shows any red/yellow issues (stale >20h)
5. Kanban renders 6 columns with issue cards
6. User scans alert zone (2-5 seconds) — if all green, done
7. If red issues exist, user clicks card → opens GitHub issue in new tab
8. User optionally clicks "Last healed" → views self-healing action log

**Business Rules:**
- Rule 1: Column mapping follows label state machine — `needs-triage` → Created, `copilot-triaging` → Triaging, spec PR open → Spec PR, `approved-for-build` → Approved, `goose-implementation` → Implementing, PR merged → Merged
- Rule 2: Health thresholds are 24h yellow, 48h red (matches self-healing intervention intervals)
- Rule 3: Health indicators use both color AND symbols (accessible to colorblind users)
- Rule 4: Data freshness is shown — if cache is >4h stale, display a warning
- Rule 5: Empty columns show placeholder text ("No issues at this stage")
- Rule 6: Issue cards show: issue number, title (truncated), age, health indicator
- Rule 7: Funnel stage in banner comes from loop-state.json; runway from costs.json

**Edge Cases:**
- Scenario 1: Issue has conflicting labels (e.g., both `needs-triage` and `copilot-triaging`) → Expected: Show in the more advanced stage (copilot-triaging takes priority)
- Scenario 2: GitHub API returns 403 (rate limited) → Expected: Show cached data with "API rate limited" warning
- Scenario 3: Issue was closed while dashboard was rendering → Expected: Remove from display on next refresh
- Scenario 4: 100+ issues in a single column → Expected: Show count in column header, paginate cards (show first 20)
- Scenario 5: Mobile viewport → Expected: Columns as swipeable carousel, "Spec PR" + "Approved" merged into "Review" column

### Feature: Self-Healing Circuit Breaker (Second Most Complex)

**Description:** A safety mechanism that prevents self-healing from entering infinite retry loops. Tracks consecutive failure counts per issue and per-run totals. When thresholds are exceeded, stops retrying and escalates to the founder via a `needs-human` issue.

**User Flow:**
1. Self-healing workflow detects stale issue #42 (needs-triage >24h)
2. Attempts recovery (label toggle)
3. Next cycle: issue #42 still stuck → increments failure counter to 1
4. Attempts recovery again
5. Next cycle: issue #42 still stuck → failure counter reaches 2 (threshold)
6. Creates `needs-human` issue: "Issue #42 stuck at triage after 2 self-healing attempts"
7. Stops retrying issue #42 for 24h (cooldown period)

**Business Rules:**
- Rule 1: Per-issue threshold is 2 consecutive failures before escalation
- Rule 2: Per-run threshold is 10 issues created or 5 failures → full circuit breaker
- Rule 3: Cooldown period is 24h per issue after escalation
- Rule 4: Circuit breaker resets at the start of each new self-healing cycle (no persistent disabled state)
- Rule 5: A `manual-only` label on an issue exempts it from self-healing entirely

**Edge Cases:**
- Scenario 1: Issue is fixed by a human between failure count 1 and 2 → Expected: Counter resets, no escalation
- Scenario 2: All 50 open issues are stale simultaneously → Expected: Circuit breaker fires after 10 creates, remaining issues deferred to next cycle
- Scenario 3: Founder closes the needs-human escalation issue → Expected: Self-healing resumes retrying on next cycle

## Success Metrics

### Key Performance Indicators

- **Adoption:** Self-healing workflow runs 12x/day (every 2h) with >99% run success rate within first week of deployment
- **Engagement:** Founder checks pipeline dashboard at least once per day (measured by page load), spends less than 60 seconds per visit
- **Quality:** Self-healing false positive rate <5% (actions taken on issues that weren't actually stuck). Self-healing healing success rate >90% (of detected stale issues, 90%+ are resolved without escalation)
- **Business Impact:** Founder pipeline overhead reduced from 30+ min/day to <5 min/day. Average stale issue resolution time reduced from 8h+ (next loop cycle) to <4h (2h detection + 2h retry)

### Tracking Requirements

| Event | Properties | Purpose |
|-------|------------|---------|
| self_healing_run | timestamp, checks_run, actions_taken, failures | Measure self-healing activity and reliability |
| stale_issue_detected | issue_number, label, age_hours, stage | Track which stages produce the most stalls |
| healing_action_taken | issue_number, action_type (retrigger/close/escalate), reason | Audit trail of autonomous actions |
| healing_action_outcome | issue_number, action_type, result (healed/failed/skipped) | Measure healing success rate |
| circuit_breaker_triggered | trigger_reason, issues_affected, run_id | Monitor safety mechanism activation |
| dashboard_loaded | viewport (desktop/mobile), data_freshness_seconds | Measure dashboard adoption |
| dashboard_issue_clicked | issue_number, source_column | Understand which stages founder investigates |

---

## Constraints and Assumptions

### Constraints

- **Budget:** Monthly burn is €50/month with 48 months runway. Self-healing adds ~€6/month in GitHub Actions minutes. Total impact must stay under €10/month incremental.
- **GitHub Actions free tier:** 2,000 minutes/month. Current usage ~2,225 min/month. Self-healing adds ~540 min/month. May require GitHub Pro upgrade ($7/month) if minutes are enforced.
- **GitHub API rate limits:** 5,000 requests/hour (REST), 30 requests/minute (Search). Self-healing uses ~30-65 requests per 2h cycle — well within limits.
- **No new infrastructure:** Dashboard must extend chimney (existing web app). No new services, databases, or hosting.
- **Cross-repo operation:** Self-healing runs from ai-pipeline-template but operates on issues in atvirokodosprendimai/wgmesh. Requires a Personal Access Token (PAT) with cross-repo write access.

### Assumptions

- **Chimney is extensible:** We assume chimney can add a `/pipeline` route without significant architectural changes.
- **GitHub label events are reliable:** We assume that removing and re-adding a label reliably re-triggers label-based workflows.
- **Copilot and Goose remain available:** Self-healing re-triggers these services. If they are deprecated or down for extended periods, self-healing will escalate to needs-human.
- **Solo operator:** The dashboard is designed for a single user. No multi-user, role-based, or team features are needed.
- **Public by default:** The dashboard is public. No sensitive data (assessment narratives, strategy, financials beyond runway months) is displayed.

## Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Runaway retry loop (self-healing triggers workflow that fails, re-triggers again) | High | Medium | Circuit breaker: 2-failure escalation + 24h cooldown per issue. Per-run cap of 10 creates / 5 failures. |
| GitHub API rate limiting during self-healing | Medium | Low | Budget is 0.29% of capacity. Monitor with rate-limit header checks before each major operation. Graceful exit on quota exhaustion. |
| False positive stale detection (issue appears stuck but is being actively worked) | Medium | Medium | Use `updatedAt` for "no progress" detection, not just `createdAt`. `manual-only` label exempts issues. |
| Label toggle re-triggers unintended workflows | High | Low | Existing guard conditions in copilot-triage.yml prevent double-triggering. Self-healing checks should verify guard conditions before acting. |
| Dashboard shows stale data without user knowing | Medium | Medium | Display data freshness indicator. Warn if cache >4h stale. Show "last sync" timestamp. |
| Self-healing and observation loop commit conflicts | High | Low | Self-healing writes to separate `pipeline-health-state.json`. Does NOT touch `loop-state.json` (owned by observation loop). |
| GitHub Actions minutes exceed free tier | Low | High | Monitor usage. Upgrade to GitHub Pro ($7/month) if needed. Justified by 30+ min/day time savings. |

## Open Questions

- [ ] Does wgmesh have its own copilot-triage.yml and goose-build.yml, or are they dispatched from ai-pipeline-template via repository_dispatch? (Affects how self-healing re-triggers workflows)
- [ ] What is chimney's current technology stack? (Affects dashboard implementation approach in SDD)
- [ ] Should self-healing commit its state file (pipeline-health-state.json) via PR (like the observation loop) or direct push to main? (Affects git workflow in SDD)

---

## Supporting Research

### Competitive Analysis

No direct competitors exist for AI pipeline self-healing in the solo-founder context. However, adjacent solutions include:
- **GitHub Actions health monitors** (e.g., Datadog CI Visibility, BuildPulse) — focus on CI/CD, not issue-to-code pipeline health
- **PagerDuty / OpsGenie** — alerting for infrastructure, not pipeline workflow state
- **Linear / Jira automation rules** — label-based automation exists but requires manual configuration and doesn't self-heal

This solution is differentiated by being fully deterministic (no LLM dependency), operating within GitHub Actions (zero new infra), and combining self-healing with observability in a single feature.

### User Research

Evidence from 4 RCA sessions (2026-03-15 through 2026-03-18):
- LLM observation loop missed stale `needs-triage` issues for 24h+ (session 2026-03-16)
- LLM created duplicate issues for features that already existed (RCA #458)
- Manual label toggling required 5-10 min per stuck issue
- Founder spent 30+ min reviewing GitHub board state across repositories
- Coroot disk-full outage (2026-03-17) went 42h before detection — no pipeline health alerting existed

### Market Data

- Solo founders / micro-SaaS operators are a growing segment (estimated 50K+ globally building with AI tooling)
- GitHub Actions is the dominant CI/CD platform for small teams (70%+ market share in <10 person teams)
- "Inner loop" developer productivity tooling is a $2B+ market, growing 25% annually
- Self-healing infrastructure patterns (from SRE) are well-established but rarely applied to issue management pipelines
