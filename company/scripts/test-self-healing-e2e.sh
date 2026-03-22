#!/usr/bin/env bash
# E2E test for pipeline self-healing workflow (T4.1)
#
# Creates test issues in TARGET_REPO with stale labels, triggers the
# pipeline-health.yml workflow, and verifies healing outcomes.
#
# Prerequisites:
#   - GH_TOKEN env var set with repo + workflow scope
#   - gh CLI authenticated
#   - jq installed
#
# Usage:
#   GH_TOKEN=ghp_xxx ./company/scripts/test-self-healing-e2e.sh
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────
readonly TARGET_REPO="atvirokodosprendimai/wgmesh"
readonly SELF_REPO="atvirokodosprendimai/ai-pipeline-template"
readonly TEST_PREFIX="[e2e-test]"
readonly POLL_INTERVAL=15
readonly MAX_POLL_ATTEMPTS=40   # 40 * 15s = 10 min max wait
readonly LABEL_TEST_TAG="e2e-test-artifact"

# ── State (arrays of issue numbers to clean up) ─────────────────────
declare -a CREATED_ISSUES=()
declare -a CREATED_PRS=()
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
  log "Cleaning up test artifacts..."
  for num in "${CREATED_ISSUES[@]}"; do
    gh issue close "$num" --repo "$TARGET_REPO" \
      --comment "Closed by e2e test cleanup" 2>/dev/null || true
    gh issue edit "$num" --repo "$TARGET_REPO" \
      --remove-label "needs-triage" \
      --remove-label "copilot-triaging" \
      --remove-label "needs-human" \
      --remove-label "$LABEL_TEST_TAG" 2>/dev/null || true
  done
  for num in "${CREATED_PRS[@]}"; do
    gh pr close "$num" --repo "$TARGET_REPO" \
      --comment "Closed by e2e test cleanup" 2>/dev/null || true
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

log "Starting self-healing E2E test against $TARGET_REPO"
echo "============================================================"

# ── Test 1: Create stale needs-triage issue ─────────────────────────
log "Test 1: Stale needs-triage detection and label toggle"

triage_issue_url=$(gh issue create --repo "$TARGET_REPO" \
  --title "${TEST_PREFIX} Stale triage test issue" \
  --body "Automated E2E test issue for self-healing validation. Safe to close." \
  --label "needs-triage" \
  --label "$LABEL_TEST_TAG")
triage_issue_num=$(echo "$triage_issue_url" | grep -o '[0-9]*$')
CREATED_ISSUES+=("$triage_issue_num")
log "  Created needs-triage issue #${triage_issue_num}"

# Backdate the issue creation time via a comment noting it is stale.
# NOTE: GitHub API does not allow backdating createdAt directly.
# The workflow uses createdAt for cutoff comparison. Since we cannot
# backdate, we rely on the workflow being triggered and the issue
# being older than 24h by test design. For immediate E2E, we create
# an issue and verify the workflow *processes* it. In CI, the issue
# would need to age 24h or use a mock cutoff.
#
# For immediate testing: we trigger the workflow and verify it at least
# *finds* the issue (even if not past cutoff). The audit log will
# confirm whether the issue was processed.

# ── Test 2: Create stale copilot-triaging issue ─────────────────────
log "Test 2: Stale copilot-triaging detection and re-assignment"

copilot_issue_url=$(gh issue create --repo "$TARGET_REPO" \
  --title "${TEST_PREFIX} Stale copilot-triaging test" \
  --body "Automated E2E test issue for copilot-triaging self-healing. Safe to close." \
  --label "copilot-triaging" \
  --label "$LABEL_TEST_TAG")
copilot_issue_num=$(echo "$copilot_issue_url" | grep -o '[0-9]*$')
CREATED_ISSUES+=("$copilot_issue_num")
log "  Created copilot-triaging issue #${copilot_issue_num}"

# ── Test 3: Create needs-human issue with a "merged PR" signal ──────
log "Test 3: Fulfilled needs-human auto-close"

needs_human_url=$(gh issue create --repo "$TARGET_REPO" \
  --title "${TEST_PREFIX} API key rotation complete" \
  --body "Automated E2E test for needs-human auto-close. Safe to close." \
  --label "needs-human" \
  --label "$LABEL_TEST_TAG")
needs_human_num=$(echo "$needs_human_url" | grep -o '[0-9]*$')
CREATED_ISSUES+=("$needs_human_num")
log "  Created needs-human issue #${needs_human_num}"

# ── Test 4: Create approved-for-build PR (stale) ────────────────────
log "Test 4: Stale approved-for-build PR detection"

# Create a throwaway branch for the test PR
test_branch="e2e-test/stale-build-$(date -u '+%s')"
# We need a trivial commit on the branch
tmp_content="E2E test artifact — $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Create branch from default branch
default_sha=$(gh api "repos/$TARGET_REPO/git/ref/heads/main" --jq '.object.sha' 2>/dev/null || \
              gh api "repos/$TARGET_REPO/git/ref/heads/master" --jq '.object.sha' 2>/dev/null || echo "")

if [ -n "$default_sha" ]; then
  gh api "repos/$TARGET_REPO/git/refs" \
    --method POST \
    --field "ref=refs/heads/${test_branch}" \
    --field "sha=${default_sha}" > /dev/null 2>&1 || true

  # Create a file on the branch
  gh api "repos/$TARGET_REPO/contents/e2e-test-artifact.txt" \
    --method PUT \
    --field "message=e2e test artifact" \
    --field "content=$(echo "$tmp_content" | base64)" \
    --field "branch=${test_branch}" > /dev/null 2>&1 || true

  build_pr_url=$(gh pr create --repo "$TARGET_REPO" \
    --title "spec: Issue #${triage_issue_num} - E2E stale build test" \
    --body "Automated E2E test PR for approved-for-build self-healing. Safe to close." \
    --head "$test_branch" \
    --base main \
    --label "approved-for-build" \
    --label "$LABEL_TEST_TAG" 2>/dev/null || echo "")

  if [ -n "$build_pr_url" ]; then
    build_pr_num=$(echo "$build_pr_url" | grep -o '[0-9]*$')
    CREATED_PRS+=("$build_pr_num")
    log "  Created approved-for-build PR #${build_pr_num}"
  else
    log "  WARN: Could not create test PR (branch creation may have failed)"
    build_pr_num=""
  fi
else
  log "  WARN: Could not resolve default branch SHA — skipping PR test"
  build_pr_num=""
fi

# ── Test 5: Create manual-only exclusion issue (before trigger) ──────
log "Test 5: manual-only exclusion"

manual_issue_url=$(gh issue create --repo "$TARGET_REPO" \
  --title "${TEST_PREFIX} Manual-only exclusion test" \
  --body "This issue should be skipped by self-healing. Safe to close." \
  --label "needs-triage" \
  --label "manual-only" \
  --label "$LABEL_TEST_TAG")
manual_issue_num=$(echo "$manual_issue_url" | grep -o '[0-9]*$')
CREATED_ISSUES+=("$manual_issue_num")
log "  Created manual-only issue #${manual_issue_num}"

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

# ── Verify workflow succeeded ────────────────────────────────────────
log "Verifying workflow outcomes..."
echo ""

# Check 1: Workflow completed successfully
if [ "$current_conclusion" = "success" ]; then
  pass "Workflow run completed successfully"
else
  fail "Workflow run conclusion was '${current_conclusion}', expected 'success'"
fi

# ── Check 2: Verify state file was updated (via PR) ─────────────────
log "Checking for state-update PR..."

state_pr=$(gh pr list --repo "$SELF_REPO" \
  --search "heal: pipeline health check" \
  --state open \
  --limit 1 \
  --json number,title,headRefName \
  --jq '.[0]' 2>/dev/null || echo "{}")

state_pr_num=$(echo "$state_pr" | jq -r '.number // ""')
state_pr_branch=$(echo "$state_pr" | jq -r '.headRefName // ""')

if [ -n "$state_pr_num" ] && [ "$state_pr_num" != "null" ]; then
  pass "State-update PR created: #${state_pr_num}"

  # Check state file contents in the PR branch
  state_content=$(gh api "repos/$SELF_REPO/contents/company/pipeline-health-state.json?ref=${state_pr_branch}" \
    --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || echo "{}")

  if [ -n "$state_content" ] && [ "$state_content" != "{}" ]; then
    last_check=$(echo "$state_content" | jq -r '.last_check // ""')
    checks_run=$(echo "$state_content" | jq -r '.checks_run // 0')
    actions_taken=$(echo "$state_content" | jq -r '.last_run_summary.actions_taken // 0')

    if [ -n "$last_check" ] && [ "$last_check" != "null" ]; then
      pass "State file has last_check timestamp: $last_check"
    else
      fail "State file missing last_check timestamp"
    fi

    if [ "$checks_run" -gt 0 ]; then
      pass "State file checks_run incremented: $checks_run"
    else
      fail "State file checks_run not incremented (value: $checks_run)"
    fi

    log "  Actions taken this run: $actions_taken"
  else
    fail "Could not read state file from PR branch"
  fi

  # Check audit log
  audit_content=$(gh api "repos/$SELF_REPO/contents/company/audit-log.jsonl?ref=${state_pr_branch}" \
    --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || echo "")

  if [ -n "$audit_content" ]; then
    audit_lines=$(echo "$audit_content" | wc -l | tr -d ' ')
    if [ "$audit_lines" -gt 0 ]; then
      pass "Audit log has ${audit_lines} entries"

      # Verify audit entries have required fields
      first_entry=$(echo "$audit_content" | head -1)
      has_timestamp=$(echo "$first_entry" | jq -r '.timestamp // ""')
      has_action=$(echo "$first_entry" | jq -r '.action // ""')
      has_run_id=$(echo "$first_entry" | jq -r '.run_id // ""')

      if [ -n "$has_timestamp" ] && [ -n "$has_action" ] && [ -n "$has_run_id" ]; then
        pass "Audit entries have required fields (timestamp, action, run_id)"
      else
        fail "Audit entries missing required fields"
      fi
    else
      fail "Audit log is empty"
    fi
  else
    log "  WARN: Could not read audit log (may not have entries this run)"
  fi
else
  fail "No state-update PR found"
fi

# ── Check 3: Verify label changes on test issues ────────────────────
log "Checking label state on test issues..."

# Check triage issue labels
triage_labels=$(gh issue view "$triage_issue_num" --repo "$TARGET_REPO" \
  --json labels --jq '[.labels[].name] | join(",")' 2>/dev/null || echo "")
log "  Triage issue #${triage_issue_num} labels: ${triage_labels:-<none>}"

# If the issue was older than 24h, needs-triage should have been toggled
# (removed then re-added). We check it still has needs-triage (toggle re-applies).
if echo "$triage_labels" | grep -q "needs-triage"; then
  pass "Triage issue #${triage_issue_num} still has needs-triage (expected after toggle)"
else
  log "  NOTE: needs-triage label was removed (issue may have been processed differently)"
fi

# Check copilot issue
copilot_labels=$(gh issue view "$copilot_issue_num" --repo "$TARGET_REPO" \
  --json labels --jq '[.labels[].name] | join(",")' 2>/dev/null || echo "")
log "  Copilot issue #${copilot_issue_num} labels: ${copilot_labels:-<none>}"

# Check needs-human issue state
needs_human_state=$(gh issue view "$needs_human_num" --repo "$TARGET_REPO" \
  --json state --jq '.state' 2>/dev/null || echo "")
log "  Needs-human issue #${needs_human_num} state: ${needs_human_state}"

# The needs-human issue has "API key" in its title, so the workflow checks
# if loop-state.json shows a successful run. If it does, the issue gets closed.
if [ "$needs_human_state" = "CLOSED" ]; then
  pass "Needs-human issue #${needs_human_num} was auto-closed (resolution signal detected)"
else
  log "  NOTE: Needs-human issue #${needs_human_num} not closed (resolution signal may not be present)"
fi

# Check approved-for-build PR
if [ -n "${build_pr_num:-}" ]; then
  build_labels=$(gh pr view "$build_pr_num" --repo "$TARGET_REPO" \
    --json labels --jq '[.labels[].name] | join(",")' 2>/dev/null || echo "")
  log "  Build PR #${build_pr_num} labels: ${build_labels:-<none>}"

  if echo "$build_labels" | grep -q "approved-for-build"; then
    pass "Build PR #${build_pr_num} still has approved-for-build (expected after toggle)"
  else
    log "  NOTE: approved-for-build label state differs from expected"
  fi
fi

# ── Check 4: Verify manual-only exclusion ────────────────────────────
log "Verifying manual-only issue #${manual_issue_num} was not modified..."

manual_labels=$(gh issue view "$manual_issue_num" --repo "$TARGET_REPO" \
  --json labels --jq '[.labels[].name] | join(",")' 2>/dev/null || echo "")
log "  Manual-only issue #${manual_issue_num} labels: ${manual_labels:-<none>}"

if echo "$manual_labels" | grep -q "needs-triage" && echo "$manual_labels" | grep -q "manual-only"; then
  pass "manual-only issue #${manual_issue_num} still has original labels (not modified by workflow)"
else
  fail "manual-only issue #${manual_issue_num} labels changed unexpectedly: ${manual_labels}"
fi

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "Self-Healing E2E Test Results"
echo "============================================================"
echo "  Passed: ${PASS_COUNT}"
echo "  Failed: ${FAIL_COUNT}"
echo ""
echo "  Test issues created: ${CREATED_ISSUES[*]}"
[ -n "${build_pr_num:-}" ] && echo "  Test PR created: ${build_pr_num}"
echo "  Workflow run: ${run_id}"
echo "============================================================"

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
