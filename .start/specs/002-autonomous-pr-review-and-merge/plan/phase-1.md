---
title: "Phase 1: Core Script Foundation"
status: completed
version: "1.0"
phase: 1
---

# Phase 1: Core Script Foundation

## Phase Context

**GATE**: Read all referenced files before starting this phase.

**Specification References**:
- `[ref: SDD/Constraints; lines: CON-1 through CON-5]`
- `[ref: SDD/Building Block View]` — component diagram, directory map
- `[ref: SDD/Runtime View/Primary Flow]` — clean review -> auto-merge sequence
- `[ref: SDD/Implementation Examples]` — poll-review-merge loop, guardrails, Andon error handling

**Key Decisions**:
- ADR-2: Single script `company/scripts/pr-review-merge.sh`
- ADR-4: Squash merge via `gh pr merge --squash --admin --delete-branch`
- ADR-5: Never merge without review (6 min timeout -> escalate)
- ADR-6: Honor `manual-only` label

**Dependencies**:
- None (first phase)
- Requires: `company/scripts/sanitise.sh` exists (already present)
- Requires: `company/audit-log.jsonl` exists (already present)

---

## Tasks

Establishes the core review-merge script capable of handling the happy path: detect review, check guardrails, merge or escalate. No fix loop yet (Phase 2).

- [ ] **T1.1 Script skeleton with Andon infrastructure** `[activity: backend-scripting]`

  1. Prime: Read CONSTITUTION.md Andon principle + QUAL-1 + QUAL-5. Read SDD/Implementation Examples/Andon-Compliant Error Handling. Study `company/scripts/sanitise.sh` for script conventions. `[ref: SDD/Cross-Cutting Concepts/System-Wide Patterns]`
  2. Test: Script starts with `set -euo pipefail`; ERRORS counter initializes to 0; `log_audit()` appends valid JSONL to audit log; `escalate()` produces `::warning::` annotation + increments ERRORS + calls sanitise.sh + adds label + posts comment; circuit breaker triggers at ERRORS >= 5
  3. Implement: Create `company/scripts/pr-review-merge.sh` with: shebang, strict mode, env var defaults (PR_MAX_LINES, MAX_RETRY_COUNT, APPROVED_AUTHORS, POLL_INTERVAL, POLL_MAX_ATTEMPTS, REVIEW_WINDOWS, PROTECTED_PATHS, SECURITY_KEYWORDS), `log_audit()` function, `escalate()` function, circuit breaker check
  4. Validate: `shellcheck company/scripts/pr-review-merge.sh` passes; script is executable; audit log output is valid JSON
  5. Success: Script skeleton passes shellcheck `[ref: SDD/Quality Requirements/Reliability]`; Andon infrastructure verified `[ref: PRD/AC-5.1]`

- [ ] **T1.2 Copilot review polling** `[activity: backend-scripting]`

  1. Prime: Read SDD/Runtime View/Primary Flow sequence diagram. Read `docs/solutions/integration-issues/github-app-reviews-dont-trigger-workflows.md`. Study pipeline-health.yml lines 746-764 for existing poll pattern. `[ref: SDD/Implementation Examples/Poll-Review-Merge Core Loop]`
  2. Test: `poll_for_review()` returns 0 when review exists; returns 1 after max attempts; respects POLL_INTERVAL and POLL_MAX_ATTEMPTS; two poll windows are attempted before timeout; `manual-only` label check exits 0 early
  3. Implement: Add `check_manual_only()`, `poll_for_review()`, `check_inline_comments()` functions. Main flow: check manual-only -> poll window 1 -> poll window 2 -> timeout escalation. Use `gh api repos/${TARGET_REPO}/pulls/${PR_NUMBER}/reviews` and `.../comments`.
  4. Validate: Functions match SDD polling specification; poll parameters configurable via env vars
  5. Success: Review detected within poll window `[ref: PRD/AC-1.1]`; manual-only label skips automation `[ref: PRD/AC-1.4]`; timeout after 2 windows escalates `[ref: PRD/AC-1.3]`

- [ ] **T1.3 Guardrail gate** `[activity: backend-scripting]` `[parallel: true]`

  1. Prime: Read SDD/Runtime View/Complex Logic: Guardrail Evaluation Order including traced walkthrough table. Read SDD/Application Data Models for GuardrailConfig fields. `[ref: SDD/Implementation Examples/Guardrail Checks]`
  2. Test: Author not in APPROVED_AUTHORS -> escalate; protected path modified -> escalate; PR size > PR_MAX_LINES -> escalate; security keyword in diff -> escalate; CI check failed -> escalate; all checks pass -> return 0; guardrails short-circuit on first failure; order matches SDD (cheapest first)
  3. Implement: Add `run_guardrails()` function with 5 checks in order: author, protected paths, size, security keywords, CI status. Each failure calls `escalate()` and returns 1. Use `gh pr view`, `gh pr diff`, `gh api .../check-runs`.
  4. Validate: All 6 traced walkthrough rows from SDD produce expected results; shellcheck passes
  5. Success: Size guardrail works `[ref: PRD/AC-4.1]`; author check works `[ref: PRD/AC-4.3]`; security keywords caught `[ref: PRD/AC-4.4]`; workflow files blocked `[ref: PRD/AC-4.5]`; CI check enforced `[ref: PRD/AC-4.2]`; thresholds configurable via env `[ref: PRD/AC-4.5]`

- [ ] **T1.4 Merge execution** `[activity: backend-scripting]`

  1. Prime: Read SDD/Runtime View/Primary Flow merge step. Read `docs/patterns/workflow-self-merge.md` for existing pattern. `[ref: SDD/Architecture Decisions/ADR-4]`
  2. Test: `merge_pr()` calls `gh pr merge --squash --admin --delete-branch`; on success, logs `pr_auto_merged` to audit; on conflict, retries once after 10s; on second failure, escalates with "merge conflict"; on PR already merged (no-op), exits cleanly
  3. Implement: Add `merge_pr()` function. Check PR state before merge. Execute merge with retry. Verify merge succeeded by checking PR state after. Log outcome.
  4. Validate: Merge function handles all 3 outcomes (success, conflict-retry, failure-escalate)
  5. Success: Clean PR merges automatically `[ref: PRD/AC-2.1, AC-2.2]`; merge conflict handled `[ref: PRD/AC-2.4]`; action logged `[ref: PRD/AC-2.4, AC-5.1]`

- [ ] **T1.5 Phase 1 Validation** `[activity: validate]`

  - Wire main flow: manual-only check -> poll -> guardrails -> merge. Run `shellcheck`. Verify script handles the complete happy path (clean review -> guardrails pass -> merge) and all escalation paths (timeout, guardrail fail, merge conflict). Test audit log entries are valid JSONL. Verify all env var defaults work.
  - Success:
    - [ ] Script passes `shellcheck` with zero warnings `[ref: SDD/Quality Requirements/Testability]`
    - [ ] Happy path produces `pr_auto_merged` audit entry `[ref: PRD/AC-2.1]`
    - [ ] Each escalation path produces correct `pr_escalated` audit entry `[ref: PRD/AC-5.1]`
    - [ ] Circuit breaker activates at 5 errors `[ref: SDD/Acceptance Criteria/Error Handling]`
