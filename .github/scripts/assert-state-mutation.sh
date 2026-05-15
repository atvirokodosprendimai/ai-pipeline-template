#!/usr/bin/env bash
set -euo pipefail

PRE_RUN_LAST_CHECK="${1:-}"
SECOND_ARG="${2:-}"
STATE_FILE="${STATE_FILE:-}"
POST_RUN_LAST_CHECK_ARG=""
GH_REPO="${GH_REPO:-${GITHUB_REPOSITORY:-${REPO:-}}}"
DRY_RUN="${SUPERVISOR_ASSERT_DRY_RUN:-0}"
TITLE="supervisor-dead: pipeline-health frozen"

if [ -z "$STATE_FILE" ]; then
  case "$SECOND_ARG" in
    "")
      STATE_FILE="company/pipeline-health-state.json"
      ;;
    */*|*.json)
      STATE_FILE="$SECOND_ARG"
      ;;
    *)
      STATE_FILE="company/pipeline-health-state.json"
      POST_RUN_LAST_CHECK_ARG="$SECOND_ARG"
      ;;
  esac
else
  POST_RUN_LAST_CHECK_ARG="$SECOND_ARG"
fi

if [ -z "$PRE_RUN_LAST_CHECK" ]; then
  echo "error: pre-run last_check argument is required" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

open_or_update_supervisor_dead() {
  local reason="$1"
  local count="$2"
  local body
  body="pipeline-health did not prove state mutation. Reason: ${reason}. consecutive_no_mutation_runs=${count}."

  if [ "$DRY_RUN" = "1" ]; then
    if [ -n "${SUPERVISOR_ASSERT_LOG:-}" ]; then
      if [ -s "$SUPERVISOR_ASSERT_LOG" ] && grep -q '^CREATE supervisor-dead ' "$SUPERVISOR_ASSERT_LOG"; then
        printf 'COMMENT supervisor-dead reason=%s count=%s\n' "$reason" "$count" >> "$SUPERVISOR_ASSERT_LOG"
      else
        printf 'CREATE supervisor-dead reason=%s count=%s\n' "$reason" "$count" >> "$SUPERVISOR_ASSERT_LOG"
      fi
    fi
    return 0
  fi

  if [ -z "${GH_TOKEN:-}" ]; then
    echo "warning: GH_TOKEN missing; cannot open supervisor-dead issue" >&2
    return 0
  fi
  if [ -z "$GH_REPO" ]; then
    echo "warning: GH_REPO or GITHUB_REPOSITORY missing; cannot open supervisor-dead issue" >&2
    return 0
  fi

  issues_json="$tmpdir/supervisor-dead-issues.json"
  gh issue list --repo "$GH_REPO" --search "$TITLE in:title is:open" --json number,title > "$issues_json"
  matches="$(jq --arg title "$TITLE" '[.[] | select(.title == $title)]' "$issues_json")"
  match_count="$(jq 'length' <<< "$matches")"

  if [ "$match_count" -eq 0 ]; then
    gh issue create --repo "$GH_REPO" --title "$TITLE" --body "$body" --label needs-human
  else
    issue_number="$(jq -r '.[0].number' <<< "$matches")"
    gh issue comment "$issue_number" --repo "$GH_REPO" --body "Still frozen: ${body}"
  fi
}

write_no_mutation_state() {
  local count="$1"
  local reason="$2"
  local now
  now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  if [ -f "$STATE_FILE" ] && jq empty "$STATE_FILE" >/dev/null 2>&1; then
    jq --argjson count "$count" --arg ts "$now" --arg reason "$reason" '
      .consecutive_no_mutation_runs = $count
      | .last_mutation_asserted_at = $ts
      | .last_mutation_assertion = {
          status: "failed",
          reason: $reason,
          checked_at: $ts
        }
    ' "$STATE_FILE" > "$tmpdir/state.json"
  else
    jq -n --argjson count "$count" --arg ts "$now" --arg reason "$reason" '
      {
        last_check: null,
        consecutive_no_mutation_runs: $count,
        last_mutation_asserted_at: $ts,
        last_mutation_assertion: {
          status: "failed",
          reason: $reason,
          checked_at: $ts
        }
      }
    ' > "$tmpdir/state.json"
  fi
  mkdir -p "$(dirname "$STATE_FILE")"
  mv "$tmpdir/state.json" "$STATE_FILE"
}

if [ ! -f "$STATE_FILE" ]; then
  write_no_mutation_state 1 "state-file-missing"
  echo "error: state file missing: $STATE_FILE" >&2
  exit 1
fi

if ! jq empty "$STATE_FILE" >/dev/null 2>&1; then
  write_no_mutation_state 2 "state-file-malformed"
  open_or_update_supervisor_dead "state-file-malformed" 2
  echo "error: malformed state file: $STATE_FILE" >&2
  exit 1
fi

if [ -n "$POST_RUN_LAST_CHECK_ARG" ]; then
  POST_RUN_LAST_CHECK="$POST_RUN_LAST_CHECK_ARG"
else
  POST_RUN_LAST_CHECK="$(jq -r '.last_check // ""' "$STATE_FILE")"
fi

if [ "$POST_RUN_LAST_CHECK" != "$PRE_RUN_LAST_CHECK" ] && [ -n "$POST_RUN_LAST_CHECK" ]; then
  now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  jq --arg ts "$now" '
    .consecutive_no_mutation_runs = 0
    | .last_mutation_asserted_at = $ts
    | .last_mutation_assertion = {
        status: "passed",
        checked_at: $ts
      }
  ' "$STATE_FILE" > "$tmpdir/state.json"
  mv "$tmpdir/state.json" "$STATE_FILE"
  echo "PASS: pipeline-health state advanced from $PRE_RUN_LAST_CHECK to $POST_RUN_LAST_CHECK"
  exit 0
fi

prior_count="$(jq -r '.consecutive_no_mutation_runs // 0' "$STATE_FILE")"
if ! [[ "$prior_count" =~ ^[0-9]+$ ]]; then
  prior_count=0
fi
new_count=$((prior_count + 1))

write_no_mutation_state "$new_count" "last_check-not-advanced"

if [ "$new_count" -ge 2 ]; then
  open_or_update_supervisor_dead "last_check-not-advanced" "$new_count"
fi

echo "error: pipeline-health state did not advance beyond $PRE_RUN_LAST_CHECK (consecutive=$new_count)" >&2
exit 1
