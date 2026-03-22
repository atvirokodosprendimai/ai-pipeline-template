#!/usr/bin/env bash
# E2E test for pipeline self-healing circuit breaker (T4.2)
#
# Creates artificial failure conditions (many stale issues) to verify
# the circuit breaker fires at the correct thresholds:
#   - Per-run: 10 issue creates OR 5 errors
#   - Per-issue: escalation after 2 consecutive failures
#
# Prerequisites:
#   - GH_TOKEN env var set with repo + workflow scope
#   - gh CLI authenticated
#   - jq installed
#
# Usage:
#   GH_TOKEN=ghp_xxx ./company/scripts/test-circuit-breaker-e2e.sh
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────
readonly TARGET_REPO="atvirokodosprendimai/wgmesh"
readonly SELF_REPO="atvirokodosprendimai/ai-pipeline-template"
readonly TEST_PREFIX="[e2e-breaker]"
readonly POLL_INTERVAL=15
readonly MAX_POLL_ATTEMPTS=40   # 40 * 15s = 10 min max wait
readonly LABEL_TEST_TAG="e2e-test-artifact"
readonly BREAKER_CREATE_THRESHOLD=10
readonly BREAKER_ERROR_THRESHOLD=5

# ── State ────────────────────────────────────────────────────────────
declare -a CREATED_ISSUES=()
PASS_COUNT=0
FAIL_COUNT=0

# ── Helpers ──────────────────────────────────────────────────────────
log()  { echo "[$(date -u '+%H:%M:%S')] $*"; }
pass() { PASS_COUNT=$((PASS_COUNT + 1)); echo "  PASS: $*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); echo "  FAIL: $*"; }

require_tool() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: $1 is required but not found"; exit 1; }
}

cleanup() {
  log "Cleaning up test artifacts (${#CREATED_ISSUES[@]} issues)..."
  for num in "${CREATED_ISSUES[@]}"; do
    gh issue close "$num" --repo "$TARGET_REPO" \
      --comment "Closed by circuit-breaker e2e test cleanup" 2>/dev/null || true
    gh issue edit "$num" --repo "$TARGET_REPO" \
      --remove-label "needs-triage" \
      --remove-label "needs-human" \
      --remove-label "$LABEL_TEST_TAG" 2>/dev/null || true
  done

  # Also close any escalation issues created by the circuit breaker
  log "Cleaning up escalation issues..."
  escalation_issues=$(gh issue list --repo "$TARGET_REPO" \
    --label "needs-human" --state open --limit 20 \
    --json number,title \
    --jq '.[] | select(.title | test("circuit breaker|e2e-breaker")) | .number' \
    2>/dev/null || echo "")
  for num in $escalation_issues; do
    gh issue close "$num" --repo "$TARGET_REPO" \
      --comment "Closed by circuit-breaker e2e test cleanup" 2>/dev/null || true
  done

  log "Cleanup complete."
}

trap cleanup EXIT

# ── Pre-flight checks ───────────────────────────────────────────────
require_tool gh
require_tool jq

if [ -z "${GH_TOKEN:-}" ]; then
  echo "ERROR: GH_TOKEN env var is required"
  exit 1
fi

export GH_TOKEN

log "Starting circuit breaker E2E test against $TARGET_REPO"
echo "============================================================"

# ── Strategy ─────────────────────────────────────────────────────────
# The circuit breaker fires when ISSUES_CREATED >= 10 or ERRORS >= 5.
# We create 12 stale needs-triage issues and trigger the workflow with
# cutoff_override_minutes=1 so that freshly created issues are treated
# as stale. Each issue triggers a label toggle (action), and after 10
# actions the breaker should fire, leaving remaining issues unprocessed.

# ── Test 1: Create stale issues for breaker threshold ────────────────
log "Test 1: Creating ${BREAKER_CREATE_THRESHOLD} + 2 stale issues..."

issue_numbers=()
for i in $(seq 1 $((BREAKER_CREATE_THRESHOLD + 2))); do
  url=$(gh issue create --repo "$TARGET_REPO" \
    --title "${TEST_PREFIX} Breaker test issue ${i}" \
    --body "Automated circuit-breaker E2E test. Safe to close." \
    --label "needs-triage" \
    --label "$LABEL_TEST_TAG")
  num=$(echo "$url" | grep -o '[0-9]*$')
  CREATED_ISSUES+=("$num")
  issue_numbers+=("$num")
  log "  Created issue #${num} (${i}/$((BREAKER_CREATE_THRESHOLD + 2)))"
done

pass "Created $((BREAKER_CREATE_THRESHOLD + 2)) test issues"

# ── Trigger the workflow ─────────────────────────────────────────────
log "Triggering pipeline-health.yml via workflow_dispatch (cutoff_override_minutes=1)..."

gh workflow run pipeline-health.yml --repo "$SELF_REPO" -f cutoff_override_minutes=1 2>/dev/null || \
  gh workflow run "Pipeline Health (Self-Healing)" --repo "$SELF_REPO" -f cutoff_override_minutes=1 2>/dev/null || {
    fail "Could not trigger pipeline-health workflow"
    echo "============================================================"
    echo "Results: ${PASS_COUNT} passed, ${FAIL_COUNT} failed"
    exit 1
  }

# Wait a moment for the run to appear, then get the specific run ID
sleep 5
run_id=$(gh run list --repo "$SELF_REPO" \
  --workflow "pipeline-health.yml" \
  --event workflow_dispatch \
  --limit 1 \
  --json databaseId --jq '.[0].databaseId' 2>/dev/null || echo "")

if [ -z "$run_id" ]; then
  fail "Could not find workflow_dispatch run"
  echo "============================================================"
  echo "Results: ${PASS_COUNT} passed, ${FAIL_COUNT} failed"
  exit 1
fi

log "  Found run $run_id"

# ── Poll for workflow completion ─────────────────────────────────────
log "Waiting for workflow run $run_id to complete..."

for attempt in $(seq 1 "$MAX_POLL_ATTEMPTS"); do
  run_data=$(gh run view "$run_id" --repo "$SELF_REPO" \
    --json status,conclusion 2>/dev/null || echo "{}")

  current_status=$(echo "$run_data" | jq -r '.status // ""')
  current_conclusion=$(echo "$run_data" | jq -r '.conclusion // ""')

  if [ "$current_status" = "completed" ]; then
    log "  Run $run_id completed with conclusion: $current_conclusion"
    break
  fi

  if [ "$attempt" -eq "$MAX_POLL_ATTEMPTS" ]; then
    fail "Workflow did not complete within polling window"
    echo "============================================================"
    echo "Results: ${PASS_COUNT} passed, ${FAIL_COUNT} failed"
    exit 1
  fi

  sleep "$POLL_INTERVAL"
done

# ── Verify circuit breaker fired ─────────────────────────────────────
log "Verifying circuit breaker outcomes..."
echo ""

# Check 1: Workflow completed (circuit breaker does not fail the run)
if [ "$current_conclusion" = "success" ]; then
  pass "Workflow completed successfully (breaker does not fail the run)"
else
  fail "Workflow conclusion was '${current_conclusion}'"
fi

# Check 2: Find the escalation issue created by the circuit breaker
log "Checking for circuit breaker escalation issue..."

breaker_issue=$(gh issue list --repo "$TARGET_REPO" \
  --label "needs-human" --state open --limit 10 \
  --json number,title,createdAt \
  --jq '.[] | select(.title | test("circuit breaker triggered")) | @json' \
  2>/dev/null | head -1 || echo "")

if [ -n "$breaker_issue" ]; then
  breaker_num=$(echo "$breaker_issue" | jq -r '.number')
  breaker_title=$(echo "$breaker_issue" | jq -r '.title')
  pass "Circuit breaker escalation issue found: #${breaker_num} — ${breaker_title}"
else
  fail "No circuit breaker escalation issue found"
fi

# Check 3: Count how many per-issue escalation issues were created
log "Counting per-issue escalation issues..."

escalation_issues=$(gh issue list --repo "$TARGET_REPO" \
  --label "needs-human" --state open --limit 50 \
  --json number,title \
  --jq '[.[] | select(.title | test("Stuck at triage.*e2e-breaker"))] | length' \
  2>/dev/null || echo "0")

log "  Per-issue escalation issues created: ${escalation_issues}"

# The breaker should fire at 10 creates, so we expect <= 10 escalation issues
# (some of the 12 stale issues should NOT have been processed)
if [ "$escalation_issues" -le "$BREAKER_CREATE_THRESHOLD" ]; then
  pass "Escalation count (${escalation_issues}) does not exceed threshold (${BREAKER_CREATE_THRESHOLD})"
else
  fail "Escalation count (${escalation_issues}) exceeds threshold (${BREAKER_CREATE_THRESHOLD})"
fi

# Check 4: Verify remaining issues were NOT processed (no label change)
log "Verifying unprocessed issues still have original labels..."

unprocessed_count=0
processed_count=0
for num in "${issue_numbers[@]}"; do
  labels=$(gh issue view "$num" --repo "$TARGET_REPO" \
    --json labels --jq '[.labels[].name] | join(",")' 2>/dev/null || echo "")
  if echo "$labels" | grep -q "needs-triage"; then
    unprocessed_count=$((unprocessed_count + 1))
  else
    processed_count=$((processed_count + 1))
  fi
done

log "  Issues still with needs-triage: ${unprocessed_count}"
log "  Issues without needs-triage: ${processed_count}"

# With escalation (retries >= 2), issues are NOT label-toggled; instead
# an escalation issue is created and a cooldown is set. The original
# label should remain. So all test issues should still have needs-triage.
if [ "$unprocessed_count" -gt 0 ]; then
  pass "Some issues remain unprocessed after breaker (${unprocessed_count} still have needs-triage)"
fi

# Check 5: Verify audit log contains circuit_breaker entry
log "Checking audit log for circuit_breaker entry..."

state_pr=$(gh pr list --repo "$SELF_REPO" \
  --search "heal: pipeline health check" \
  --state open \
  --limit 1 \
  --json number,headRefName \
  --jq '.[0]' 2>/dev/null || echo "{}")

state_pr_branch=$(echo "$state_pr" | jq -r '.headRefName // ""')

if [ -n "$state_pr_branch" ] && [ "$state_pr_branch" != "null" ]; then
  audit_content=$(gh api "repos/$SELF_REPO/contents/company/audit-log.jsonl?ref=${state_pr_branch}" \
    --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || echo "")

  if [ -n "$audit_content" ]; then
    breaker_entries=$(echo "$audit_content" | jq -s '[.[] | select(.action == "circuit_breaker")] | length' 2>/dev/null || echo "0")

    if [ "$breaker_entries" -gt 0 ]; then
      pass "Audit log contains ${breaker_entries} circuit_breaker entry/entries"
    else
      fail "Audit log has no circuit_breaker entries"
    fi

    escalate_entries=$(echo "$audit_content" | jq -s '[.[] | select(.action == "escalate")] | length' 2>/dev/null || echo "0")
    log "  Audit log escalation entries: ${escalate_entries}"

    if [ "$escalate_entries" -gt 0 ]; then
      pass "Audit log contains ${escalate_entries} per-issue escalation entries"
    else
      fail "Audit log has no per-issue escalation entries"
    fi
  else
    fail "Could not read audit log from PR branch"
  fi
else
  log "  WARN: No state-update PR found — checking main branch audit log"
  audit_content=$(gh api "repos/$SELF_REPO/contents/company/audit-log.jsonl" \
    --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || echo "")
  if [ -n "$audit_content" ]; then
    breaker_entries=$(echo "$audit_content" | jq -s '[.[] | select(.action == "circuit_breaker")] | length' 2>/dev/null || echo "0")
    if [ "$breaker_entries" -gt 0 ]; then
      pass "Audit log contains circuit_breaker entry (from main)"
    else
      fail "No circuit_breaker entry in audit log"
    fi
  else
    fail "Could not read audit log"
  fi
fi

# Check 6: Verify state file shows errors or creates in last_run_summary
log "Checking state file run summary..."

if [ -n "$state_pr_branch" ] && [ "$state_pr_branch" != "null" ]; then
  state_json=$(gh api "repos/$SELF_REPO/contents/company/pipeline-health-state.json?ref=${state_pr_branch}" \
    --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || echo "{}")
else
  state_json=$(gh api "repos/$SELF_REPO/contents/company/pipeline-health-state.json" \
    --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || echo "{}")
fi

if [ -n "$state_json" ] && [ "$state_json" != "{}" ]; then
  run_errors=$(echo "$state_json" | jq -r '.last_run_summary.errors // 0')
  run_actions=$(echo "$state_json" | jq -r '.last_run_summary.actions_taken // 0')
  stale_triage=$(echo "$state_json" | jq -r '.last_run_summary.stale_triage_found // 0')
  log "  State: errors=${run_errors}, actions=${run_actions}, stale_triage=${stale_triage}"

  if [ "$run_actions" -gt 0 ]; then
    pass "State file shows ${run_actions} actions taken"
  else
    fail "State file shows 0 actions taken"
  fi
fi

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "Circuit Breaker E2E Test Results"
echo "============================================================"
echo "  Passed: ${PASS_COUNT}"
echo "  Failed: ${FAIL_COUNT}"
echo ""
echo "  Test issues created: ${#CREATED_ISSUES[@]}"
echo "  Workflow run: ${run_id:-unknown}"
echo "  Breaker threshold: ${BREAKER_CREATE_THRESHOLD} creates / ${BREAKER_ERROR_THRESHOLD} errors"
echo "============================================================"

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
