#!/usr/bin/env bash
# Autonomous PR review and merge script.
# Polls for Copilot review, enforces guardrails, and merges bot-authored PRs.
# Requires: GH_TOKEN, PR_NUMBER, TARGET_REPO env vars.
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment)
# ---------------------------------------------------------------------------
PR_MAX_LINES="${PR_MAX_LINES:-500}"
MAX_RETRY_COUNT="${MAX_RETRY_COUNT:-3}"
APPROVED_AUTHORS="${APPROVED_AUTHORS:-copilot-swe-agent[bot],goose[bot]}"
POLL_INTERVAL="${POLL_INTERVAL:-30}"
POLL_MAX_ATTEMPTS="${POLL_MAX_ATTEMPTS:-6}"
REVIEW_WINDOWS="${REVIEW_WINDOWS:-2}"
PROTECTED_PATHS="${PROTECTED_PATHS:-}"
SECURITY_KEYWORDS="${SECURITY_KEYWORDS:-secret,token,password,api_key,private_key,credentials,authorization}"

# ---------------------------------------------------------------------------
# Required env vars — fail fast
# ---------------------------------------------------------------------------
: "${PR_NUMBER:?PR_NUMBER must be set}"
: "${TARGET_REPO:?TARGET_REPO must be set}"
: "${GH_TOKEN:?GH_TOKEN must be set}"

# ---------------------------------------------------------------------------
# Andon infrastructure
# ---------------------------------------------------------------------------
ERRORS=0
AUDIT_LOG="company/audit-log.jsonl"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_ID="${GITHUB_RUN_ID:-local}"

# ---------------------------------------------------------------------------
# log_audit — append a JSONL entry (QUAL-6: jq for all JSON construction)
# ---------------------------------------------------------------------------
log_audit() {
  local action="$1" details="${2:-}"
  jq -nc \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg run_id "$RUN_ID" \
    --arg action "$action" \
    --arg pr_number "$PR_NUMBER" \
    --arg repo "$TARGET_REPO" \
    --arg details "$details" \
    '{timestamp: $ts, run_id: $run_id, action: $action, pr_number: $pr_number, target_repo: $repo, details: $details}' \
    >> "$AUDIT_LOG"
}

# ---------------------------------------------------------------------------
# escalate — label + comment + audit (SEC-2: sanitise before publishing)
# ---------------------------------------------------------------------------
escalate() {
  local pr="$1" reason="$2"
  echo "::warning::Escalating PR #${pr}: ${reason}"
  ERRORS=$((ERRORS + 1))

  # Sanitise the reason before posting to PR (SEC-2)
  local safe_reason
  if ! safe_reason=$(echo "$reason" | "${SCRIPT_DIR}/sanitise.sh"); then
    echo "::error::Sanitisation failed for escalation reason on PR #${pr}"
    ERRORS=$((ERRORS + 1))
    safe_reason="[content redacted — sanitisation failure]"
  fi

  # Add needs-human label (Andon: each gh command wrapped in error handling)
  if ! gh pr edit "$pr" --repo "$TARGET_REPO" --add-label "needs-human" >/dev/null 2>&1; then
    echo "::error::Failed to add needs-human label to PR #${pr}"
    ERRORS=$((ERRORS + 1))
  fi

  # Post escalation comment
  local body
  body=$(jq -nc --arg reason "$safe_reason" \
    '"## Escalated to Human Review\n\n**Reason:** " + $reason + "\n\n_Autonomous review could not resolve this PR._"')
  # body is JSON-encoded string; strip outer quotes for --body
  body="${body:1:${#body}-2}"

  if ! gh pr comment "$pr" --repo "$TARGET_REPO" --body "$body" >/dev/null 2>&1; then
    echo "::error::Failed to comment on PR #${pr}"
    ERRORS=$((ERRORS + 1))
  fi

  log_audit "escalated" "$reason"

  # Server-side PostHog event so escalation rate is queryable alongside
  # bot_pr_merged. Non-fatal — the helper itself swallows curl failures.
  if [ -x "${SCRIPT_DIR}/posthog-emit.sh" ]; then
    local escalation_props
    escalation_props=$(jq -nc \
      --arg pr "$pr" \
      --arg reason "$safe_reason" \
      '{pr_number: ($pr|tonumber), reason: $reason}')
    bash "${SCRIPT_DIR}/posthog-emit.sh" escalation_posted "pr-review-merge" "$escalation_props" || true
  fi

  check_circuit_breaker
}

# ---------------------------------------------------------------------------
# check_circuit_breaker — halt if too many errors (SEC-7)
# ---------------------------------------------------------------------------
check_circuit_breaker() {
  if [[ "$ERRORS" -ge 5 ]]; then
    echo "::error::Circuit breaker activated — ${ERRORS} errors reached threshold"
    log_audit "circuit_breaker" "Halted after ${ERRORS} errors"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# check_manual_only — skip PR if manual-only label is present (QUAL-7)
# ---------------------------------------------------------------------------
check_manual_only() {
  local pr="$1"
  local labels
  if ! labels=$(gh pr view "$pr" --repo "$TARGET_REPO" --json labels --jq '.labels[].name'); then
    echo "::error::Failed to fetch labels for PR #${pr}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    return 1
  fi

  if echo "$labels" | grep -qxF "manual-only"; then
    echo "PR #${pr} has manual-only label — skipping autonomous review"
    log_audit "skipped" "manual-only label present"
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# is_auto_state_pr — detect bot-authored auto state-update PRs that don't
# warrant Copilot review. Match title prefix AND author = pupabobas[bot] so
# a hand-crafted PR with the same title prefix still gets the full review path.
#
# Skip-eligible patterns:
#   "heal: pipeline health check ..."   — from pipeline-health.yml
#   "audit: strategy baseline ..."      — from strategy-audit.yml no-drift case
#
# NOT skip-eligible:
#   "audit: strategy drift detected ..." — drift PRs propose STRATEGY.md edits;
#     these carry --label needs-human and should be reviewed by a human, not
#     auto-merged. Drift PRs already get the full review path.
# ---------------------------------------------------------------------------
is_auto_state_pr() {
  local pr="$1"
  local meta title author
  if ! meta=$(gh pr view "$pr" --repo "$TARGET_REPO" --json title,author --jq '{title, author: .author.login}' 2>/dev/null); then
    return 1
  fi
  title=$(jq -r '.title' <<< "$meta")
  author=$(jq -r '.author' <<< "$meta")

  case "$author" in
    pupabobas|app/pupabobas|pupabobas\[bot\]) ;;
    *) return 1 ;;
  esac

  case "$title" in
    "heal: pipeline health check"*) return 0 ;;
    "audit: strategy baseline"*) return 0 ;;
    *) return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# poll_for_review — wait for Copilot review within a single poll window
# Returns 0 if review found, 1 on timeout.
# ---------------------------------------------------------------------------
poll_for_review() {
  local pr="$1" window="$2"
  local interval="$POLL_INTERVAL"
  local max_attempts="$POLL_MAX_ATTEMPTS"

  for attempt in $(seq 1 "$max_attempts"); do
    local review_count
    if ! review_count=$(gh api "repos/${TARGET_REPO}/pulls/${pr}/reviews" --jq 'length' 2>/dev/null); then
      echo "::warning::Failed to fetch reviews for PR #${pr} (window ${window}, attempt ${attempt})"
      ERRORS=$((ERRORS + 1))
      check_circuit_breaker
    else
      if [[ "$review_count" -gt 0 ]]; then
        echo "Review found for PR #${pr} after ${attempt} poll(s) (window ${window})"
        log_audit "review_detected" "Review found in window ${window}, attempt ${attempt}"
        return 0
      fi
    fi

    if [[ "$attempt" -lt "$max_attempts" ]]; then
      sleep "$interval"
    fi
  done

  echo "::warning::Review poll window ${window} expired for PR #${pr}"
  return 1
}

# ---------------------------------------------------------------------------
# check_unresolved_threads — count UNRESOLVED review threads on PR
# Uses GraphQL because the REST API has no resolved/unresolved filter.
# Outputs the unresolved count to stdout. Returns non-zero on API failure.
# ---------------------------------------------------------------------------
check_unresolved_threads() {
  local pr="$1"
  local owner repo
  owner="${TARGET_REPO%%/*}"
  repo="${TARGET_REPO##*/}"
  local count
  if ! count=$(gh api graphql \
    -F owner="$owner" \
    -F repo="$repo" \
    -F pr="$pr" \
    -f query='
      query($owner: String!, $repo: String!, $pr: Int!) {
        repository(owner: $owner, name: $repo) {
          pullRequest(number: $pr) {
            reviewThreads(first: 100) {
              pageInfo { hasNextPage }
              nodes { isResolved }
            }
          }
        }
      }' \
    --jq '
      if .data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage
      then 999
      else [.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length
      end' 2>/dev/null); then
    echo "::error::Failed to fetch review threads for PR #${pr}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    echo "0"
    return 1
  fi
  echo "$count"
}

# ---------------------------------------------------------------------------
# run_guardrails — enforce safety checks before merge (cheapest first)
# Order: author → protected paths → size → security keywords → CI status
# Short-circuits on first failure. Uses global PR_NUMBER and TARGET_REPO.
# ---------------------------------------------------------------------------
run_guardrails() {
  # 1. Author check (fastest — single field from PR metadata)
  local author
  if ! author=$(gh pr view "$PR_NUMBER" --repo "$TARGET_REPO" --json author --jq '.author.login'); then
    echo "::error::Failed to fetch PR author for PR #${PR_NUMBER}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    return 1
  fi

  # gh CLI returns "app/<slug>" for GitHub App authors, while workflow event
  # payloads pass "<slug>[bot]". Normalize both forms to the bare slug so the
  # author allowlist match works regardless of which surface produced the name.
  normalize_login() {
    local x="${1#app/}"
    printf '%s' "${x%\[bot\]}"
  }
  local author_norm
  author_norm=$(normalize_login "$author")

  local approved_found="false"
  IFS=',' read -ra approved_list <<< "$APPROVED_AUTHORS"
  for approved in "${approved_list[@]}"; do
    if [[ "$(normalize_login "$approved")" == "$author_norm" ]]; then
      approved_found="true"
      break
    fi
  done
  if [[ "$approved_found" != "true" ]]; then
    escalate "$PR_NUMBER" "Unknown author: ${author}"
    check_circuit_breaker
    return 1
  fi

  # 2. Protected paths check (fast — uses file list from PR metadata)
  local changed_files
  if ! changed_files=$(gh pr view "$PR_NUMBER" --repo "$TARGET_REPO" --json files --jq '.files[].path'); then
    echo "::error::Failed to fetch changed files for PR #${PR_NUMBER}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    return 1
  fi

  IFS=',' read -ra protected_list <<< "$PROTECTED_PATHS"
  for prefix in "${protected_list[@]}"; do
    if echo "$changed_files" | grep -q "^${prefix}"; then
      escalate "$PR_NUMBER" "Changes to protected path: ${prefix}"
      check_circuit_breaker
      return 1
    fi
  done

  # 3. Size check (fast — additions + deletions from PR metadata)
  local lines_changed
  if ! lines_changed=$(gh pr view "$PR_NUMBER" --repo "$TARGET_REPO" --json additions,deletions --jq '.additions + .deletions'); then
    echo "::error::Failed to fetch PR size for PR #${PR_NUMBER}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    return 1
  fi

  if [[ "$lines_changed" -gt "$PR_MAX_LINES" ]]; then
    escalate "$PR_NUMBER" "PR exceeds size limit (${lines_changed} lines > ${PR_MAX_LINES})"
    check_circuit_breaker
    return 1
  fi

  # 4. Security keywords check (moderate — requires diff scan)
  local diff_added
  if ! diff_added=$(gh pr diff "$PR_NUMBER" --repo "$TARGET_REPO" | grep -e '^+' | grep -v -e '^+++' || true); then
    echo "::error::Failed to fetch PR diff for PR #${PR_NUMBER}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    return 1
  fi

  IFS=',' read -ra keyword_list <<< "$SECURITY_KEYWORDS"
  for kw in "${keyword_list[@]}"; do
    if echo "$diff_added" | grep -qiF -- "$kw"; then
      escalate "$PR_NUMBER" "Security keyword detected in diff: ${kw}"
      check_circuit_breaker
      return 1
    fi
  done

  # 5. CI status check (slowest — may need to wait for CI completion)
  local head_sha
  if ! head_sha=$(gh pr view "$PR_NUMBER" --repo "$TARGET_REPO" --json headRefOid --jq '.headRefOid'); then
    echo "::error::Failed to fetch head SHA for PR #${PR_NUMBER}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    return 1
  fi

  local failed_checks
  if ! failed_checks=$(gh api "repos/${TARGET_REPO}/commits/${head_sha}/check-runs" --jq '[.check_runs[] | select(.status=="completed" and .conclusion=="failure")] | length'); then
    echo "::error::Failed to fetch CI status for PR #${PR_NUMBER}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    return 1
  fi

  if [[ "$failed_checks" -gt 0 ]]; then
    escalate "$PR_NUMBER" "CI checks failed (${failed_checks} failures)"
    check_circuit_breaker
    return 1
  fi

  # All guardrails passed
  log_audit "guardrails_passed" "All guardrails passed"
  return 0
}

# ---------------------------------------------------------------------------
# reassign_agent — re-assign copilot-swe-agent with review feedback
# ---------------------------------------------------------------------------
reassign_agent() {
  local pr="$1" attempt="$2"

  # Gather inline comment bodies as feedback for the agent
  local feedback
  if ! feedback=$(gh api "repos/${TARGET_REPO}/pulls/${pr}/comments" \
    --jq '[.[].body] | join("\n---\n")' 2>&1); then
    echo "::warning::Failed to fetch review comments for agent re-assignment on PR #${pr}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    feedback="Review comments could not be retrieved. Please review and fix any issues."
  fi

  # Truncate feedback to 500 chars to avoid API payload limits
  feedback="${feedback:0:500}"

  # Sanitise feedback before passing to API (SEC-2)
  local safe_feedback
  if ! safe_feedback=$(echo "$feedback" | "${SCRIPT_DIR}/sanitise.sh"); then
    echo "::warning::Sanitisation failed for agent feedback on PR #${pr}"
    ERRORS=$((ERRORS + 1))
    safe_feedback="Please review and fix any issues found by the code reviewer."
  fi

  # Build JSON payload with jq (QUAL-6)
  local payload
  payload=$(jq -nc \
    --arg instructions "Retry ${attempt}: Fix the review comments on PR #${pr}. Feedback: ${safe_feedback}" \
    '{assignees: ["copilot-swe-agent[bot]"], agent_assignment: {custom_instructions: $instructions}}')

  if ! gh api "repos/${TARGET_REPO}/issues/${pr}/assignees" \
    -H "X-GitHub-Api-Version:2022-11-28" \
    --method POST \
    --input - <<< "$payload" >/dev/null 2>&1; then
    echo "::error::Failed to re-assign agent for PR #${pr} (attempt ${attempt})"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
  fi

  log_audit "agent_reassigned" "Re-assigned copilot-swe-agent, attempt ${attempt}"
}

# ---------------------------------------------------------------------------
# merge_pr — squash merge with pre-check, retry on conflict, post-verify
# ---------------------------------------------------------------------------
merge_pr() {
  local pr="$1"
  local merge_delay=10

  # Pre-check: is the PR already merged or closed? (idempotency)
  local pr_state
  if ! pr_state=$(gh pr view "$pr" --repo "$TARGET_REPO" --json state --jq '.state'); then
    echo "::error::Failed to fetch PR state for PR #${pr}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
  fi

  if [[ "${pr_state:-}" == "MERGED" ]]; then
    echo "PR #${pr} is already merged"
    log_audit "merged" "PR already merged (idempotent)"
    return 0
  fi

  if [[ "${pr_state:-}" == "CLOSED" ]]; then
    echo "PR #${pr} was closed externally"
    log_audit "closed" "PR closed externally — skipping merge"
    return 0
  fi

  # Attempt merge (up to 2 tries: initial + 1 retry for conflict recovery)
  local max_merge_attempts=2
  for attempt in $(seq 1 "$max_merge_attempts"); do
    if gh pr merge "$pr" --repo "$TARGET_REPO" --squash --admin --delete-branch >/dev/null 2>&1; then
      local elapsed=$(( $(date +%s) - START_TIME ))
      echo "PR #${pr} merged successfully (attempt ${attempt}, ${elapsed}s elapsed)"
      log_audit "merged" "Squash merged on attempt ${attempt}, ${elapsed}s elapsed"

      # Post-merge verification
      local post_state
      if ! post_state=$(gh pr view "$pr" --repo "$TARGET_REPO" --json state --jq '.state'); then
        echo "::warning::Failed to verify post-merge state for PR #${pr}"
        ERRORS=$((ERRORS + 1))
        check_circuit_breaker
      elif [[ "${post_state:-}" != "MERGED" ]]; then
        escalate "$pr" "Merge command succeeded but PR still open (state: ${post_state})"
        return 1
      fi

      return 0
    fi

    echo "::warning::Merge attempt ${attempt}/${max_merge_attempts} failed for PR #${pr}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker

    if [[ "$attempt" -lt "$max_merge_attempts" ]]; then
      sleep "$merge_delay"
    fi
  done

  # Both attempts failed
  escalate "$pr" "Merge failed after retry (possible conflict)"
  return 1
}

# ---------------------------------------------------------------------------
# check_manual_push — detect non-bot commits (resets retry counter per AC-3.4)
# Returns 0 if manual push detected, 1 otherwise.
# ---------------------------------------------------------------------------
check_manual_push() {
  local pr="$1"
  local latest_author
  if ! latest_author=$(gh api "repos/${TARGET_REPO}/pulls/${pr}/commits" --jq '.[-1].author.login // empty' 2>/dev/null); then
    echo "::warning::Failed to check latest commit author for PR #${pr}"
    ERRORS=$((ERRORS + 1))
    check_circuit_breaker
    return 1  # can't determine, continue normally
  fi

  # If author is empty/null, can't determine — skip reset
  if [[ -z "$latest_author" ]]; then
    return 1
  fi

  # Check if author is NOT a known bot
  local is_bot="false"
  IFS=',' read -ra approved_list <<< "$APPROVED_AUTHORS"
  for approved in "${approved_list[@]}"; do
    if [[ "$latest_author" == "$approved" ]]; then
      is_bot="true"
      break
    fi
  done

  if [[ "$is_bot" != "true" ]]; then
    echo "Manual push detected by ${latest_author} — resetting retry counter"
    log_audit "manual_push" "Non-bot commit by ${latest_author}, retry counter reset"
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
main() {
  START_TIME=$(date +%s)
  log_audit "started" "Processing PR #${PR_NUMBER}"

  # T1.2: Manual-only check — exit early if label present
  if check_manual_only "$PR_NUMBER"; then
    exit 0
  fi

  # Auto state-update PRs (bot-authored heal:/audit: title prefixes) skip the
  # Copilot poll + retry loop. Their content is mechanical (state JSON +
  # audit-log append) so a 360s Copilot timeout + escalation comment is pure
  # noise. Guardrails still run below to protect against accidental large or
  # security-keyword diffs.
  local auto_state_pr="false"
  if is_auto_state_pr "$PR_NUMBER"; then
    auto_state_pr="true"
    log_audit "auto_state_pr" "Skipping Copilot review for trivial state-update PR"
  fi

  if [[ "$auto_state_pr" != "true" ]]; then
    # T1.2: Poll for Copilot review across configured windows
    local review_found="false"
    for window in $(seq 1 "$REVIEW_WINDOWS"); do
      if poll_for_review "$PR_NUMBER" "$window"; then
        review_found="true"
        break
      fi
    done

    if [[ "$review_found" != "true" ]]; then
      local total_seconds=$(( POLL_MAX_ATTEMPTS * POLL_INTERVAL * REVIEW_WINDOWS ))
      escalate "$PR_NUMBER" "Copilot review timeout after ${REVIEW_WINDOWS} poll windows (${total_seconds}s)"
      exit 0
    fi

    # T1.2: Inline-settling grace period.
    #
    # Copilot's review submission is two-phase: it posts the summary review
    # FIRST (creating a record with state COMMENTED that satisfies
    # poll_for_review's reviews_count > 0 check), THEN posts inline comments
    # which land as reviewThreads. Sampling threads immediately after the
    # summary lands races the inline comments — the script sees 0 unresolved
    # threads, passes guardrails, and merges. The inline comments arrive
    # too late. PR #577 (wgmesh) hit exactly this in 2026-05-08 (13 inline
    # findings posted ~24 minutes after summary; PR was already merged).
    #
    # Mitigation: take a first sample. If it shows 0 threads, sleep and
    # re-sample — the second sample is the source of truth (it is the
    # latest reading; if threads were resolved during the window, the
    # second sample correctly reflects 0). If the first sample already
    # shows >0 threads, the race is moot — skip the sleep and proceed.
    # Tunable via INLINE_GRACE_SECONDS (default 90s; set 0 to disable).
    #
    # Round-2 fixes addressed: command-substitution exit under set -e
    # (`|| true` after each call), skip-sleep on first>0, and use second
    # sample as latest source-of-truth instead of MAX.
    # Round-4 fix: capture both stdout AND exit code from
    # check_unresolved_threads. On API failure the function echoes "0"
    # and returns non-zero — masking that with `|| true` and proceeding
    # with comment_count=0 would let an unsafe merge through when thread
    # state is actually unknown. Escalate instead.
    local comment_count first_thread_count first_rc
    first_thread_count=$(check_unresolved_threads "$PR_NUMBER") && first_rc=0 || first_rc=$?
    if [[ "$first_rc" -ne 0 ]]; then
      escalate "$PR_NUMBER" "Failed to fetch review threads on first sample (rc=${first_rc}) — cannot verify clean state safely"
      exit 0
    fi
    first_thread_count="${first_thread_count:-0}"
    log_audit "inline_settling_first" "First sample: ${first_thread_count} unresolved threads"

    if [[ "$first_thread_count" -gt 0 ]]; then
      # Race is moot — inline comments already visible. Skip the settling
      # window so retry/escalation is not delayed.
      comment_count="$first_thread_count"
      log_audit "inline_no_settling_needed" "First sample > 0; skipping settling window"
    else
      # Validate INLINE_GRACE_SECONDS as a non-negative integer. Anything
      # else (empty, "90s", "0.5", garbage) falls back to the default to
      # avoid `[[ -gt ]]` errors and `sleep` failures under set -e.
      local inline_grace_seconds="${INLINE_GRACE_SECONDS:-90}"
      if ! [[ "$inline_grace_seconds" =~ ^[0-9]+$ ]]; then
        echo "::warning::INLINE_GRACE_SECONDS='${inline_grace_seconds}' is not a non-negative integer; falling back to 90s"
        inline_grace_seconds=90
      fi
      if [[ "$inline_grace_seconds" -gt 0 ]]; then
        sleep "$inline_grace_seconds"
      fi
      # Same explicit rc capture as the first sample.
      local second_rc
      comment_count=$(check_unresolved_threads "$PR_NUMBER") && second_rc=0 || second_rc=$?
      if [[ "$second_rc" -ne 0 ]]; then
        escalate "$PR_NUMBER" "Failed to fetch review threads on second sample (rc=${second_rc}) — cannot verify clean state safely"
        exit 0
      fi
      comment_count="${comment_count:-0}"
      log_audit "inline_settling_second" "Second sample after ${inline_grace_seconds}s: ${comment_count} unresolved threads"
      if [[ "$comment_count" -gt 0 ]]; then
        log_audit "inline_late_arrival" "Inline comments arrived during settling window (0 → ${comment_count})"
      fi
    fi

    # Distinct audit action so this entry is not confused with the
    # `review_detected` entry emitted by poll_for_review when the review
    # record first appears. (Round-2 finding: same action name was
    # ambiguous for log/metric consumers.)
    log_audit "review_settled" "Review settled, ${comment_count} unresolved threads after grace window"
    local retry_count=0

    while [[ "$comment_count" -gt 0 ]] && [[ "$retry_count" -lt "$MAX_RETRY_COUNT" ]]; do
      retry_count=$((retry_count + 1))
      log_audit "retry" "Retry ${retry_count}/${MAX_RETRY_COUNT} — ${comment_count} unresolved threads"

      reassign_agent "$PR_NUMBER" "$retry_count"

      # Poll for new review after agent push
      review_found="false"
      for window in $(seq 1 "$REVIEW_WINDOWS"); do
        if poll_for_review "$PR_NUMBER" "$window"; then
          review_found="true"
          break
        fi
      done

      if [[ "$review_found" != "true" ]]; then
        escalate "$PR_NUMBER" "Review timeout during retry ${retry_count}"
        exit 0
      fi

      # Check for manual push (resets retry counter per PRD/AC-3.4)
      if check_manual_push "$PR_NUMBER"; then
        retry_count=0
      fi

      comment_count=$(check_unresolved_threads "$PR_NUMBER")
    done

    if [[ "$comment_count" -gt 0 ]]; then
      escalate "$PR_NUMBER" "Retries exhausted (${MAX_RETRY_COUNT}), ${comment_count} unresolved threads remain"
      exit 0
    fi
  fi

  # T1.3: run_guardrails — short-circuits on first failure
  if ! run_guardrails; then
    exit 0  # guardrail escalated internally
  fi

  # Spec PR gate: require positive validation signal before merge.
  # spec-validation.yml runs fast (~30s) and adds approved-for-build on pass
  # or spec-needs-fix on fail. We check for both to avoid a race where we
  # merge before validation finishes.
  local pr_title
  pr_title=$(gh pr view "$PR_NUMBER" --repo "$TARGET_REPO" --json title --jq '.title' 2>/dev/null || echo "")
  if echo "$pr_title" | grep -qi "^spec:"; then
    local labels
    labels=$(gh pr view "$PR_NUMBER" --repo "$TARGET_REPO" --json labels --jq '.labels[].name' 2>/dev/null || echo "")
    if echo "$labels" | grep -qxF "spec-needs-fix"; then
      escalate "$PR_NUMBER" "Spec validation failed (spec-needs-fix label present)"
      exit 0
    fi
    if ! echo "$labels" | grep -qxF "approved-for-build"; then
      # Validation hasn't finished yet — wait and retry
      echo "Spec PR waiting for spec-validation to complete..."
      local spec_wait
      for spec_wait in $(seq 1 6); do
        sleep 30
        labels=$(gh pr view "$PR_NUMBER" --repo "$TARGET_REPO" --json labels --jq '.labels[].name' 2>/dev/null || echo "")
        if echo "$labels" | grep -qxF "spec-needs-fix"; then
          escalate "$PR_NUMBER" "Spec validation failed (spec-needs-fix label present)"
          exit 0
        fi
        if echo "$labels" | grep -qxF "approved-for-build"; then
          echo "Spec PR approved for build — proceeding to merge"
          break
        fi
        echo "  Waiting for spec-validation (attempt ${spec_wait}/6)..."
      done
      if ! echo "$labels" | grep -qxF "approved-for-build"; then
        escalate "$PR_NUMBER" "Spec validation did not complete within timeout"
        exit 0
      fi
    fi
    log_audit "spec_validated" "Spec PR passed validation (approved-for-build)"
  fi

  # T1.4: merge the PR
  if ! merge_pr "$PR_NUMBER"; then
    exit 0  # merge_pr escalated internally
  fi
}

main "$@"
