#!/usr/bin/env bash
set -euo pipefail

RANKED_JSON="${1:?Usage: publish-rank.sh <ranked-json> [state-file]}"
STATE_FILE="${2:-company/supervisor-rank-state.json}"
GH_REPO="${GH_REPO:-${GITHUB_REPOSITORY:-}}"
TITLE="supervisor-rank: top pipeline clogs"
DRY_RUN="${SUPERVISOR_PUBLISH_DRY_RUN:-0}"

if ! jq empty "$RANKED_JSON" >/dev/null 2>&1; then
  echo "error: malformed ranked JSON: $RANKED_JSON" >&2
  exit 1
fi

if [ "$DRY_RUN" != "1" ]; then
  if [ -z "$GH_REPO" ]; then
    echo "error: GH_REPO or GITHUB_REPOSITORY is required" >&2
    exit 1
  fi
  if [ -z "${GH_TOKEN:-}" ]; then
    echo "error: GH_TOKEN is required" >&2
    exit 1
  fi
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
body_file="$tmpdir/supervisor-rank-body.md"
new_state="$tmpdir/supervisor-rank-state.json"

previous_top="[]"
previous_run=0
if [ -f "$STATE_FILE" ] && jq empty "$STATE_FILE" >/dev/null 2>&1; then
  previous_top="$(jq -c '.last_run_top_ids // []' "$STATE_FILE")"
  previous_run="$(jq -r '.run_number // 0' "$STATE_FILE")"
fi

current_top="$(jq -c '[.top[0:3][]?.id]' "$RANKED_JSON")"
rank_changed="false"
if [ "$previous_top" != "[]" ] && [ "$previous_top" != "$current_top" ]; then
  rank_changed="true"
fi

generated_at="$(jq -r '.generated_at // ""' "$RANKED_JSON")"
run_number=$((previous_run + 1))

{
  echo "# supervisor-rank: top pipeline clogs"
  echo
  echo "Updated: ${generated_at:-unknown} (run #$run_number)"
  echo
  echo "## Top clogs"
  if [ "$(jq '.top | length' "$RANKED_JSON")" -eq 0 ]; then
    echo
    echo "All clear. No ranked open clogs in the current snapshot."
  else
    jq -r '.top[] |
      "\(.rank). **\(.title)** — \(.repo)#\(.number)\n" +
      "   - Stage: `\(.stage)`\n" +
      "   - Dwell x blocked: \(.dwell_hours)h x \(.downstream_blocked_count) = \(.score)\n" +
      "   - Recommended action: `\(.recommended_action // "none")`\n"' "$RANKED_JSON"
  fi
  echo
  echo "## Stage summary"
  jq -r '.stage_summary | to_entries[] | "- \(.key): \(.value)"' "$RANKED_JSON"
  echo
  echo "## Needs taxonomy"
  if [ "$(jq '.unknown | length' "$RANKED_JSON")" -eq 0 ]; then
    echo "- unknown: 0"
  else
    jq -r '.unknown[] | "- \(.repo)#\(.number): \(.title)"' "$RANKED_JSON"
  fi
  echo
  echo "## State"
  echo "- Prior top-3: \`$previous_top\`"
  echo "- Current top-3: \`$current_top\`"
  echo "- File: \`$STATE_FILE\`"
} > "$body_file"

retry_gh() {
  local attempt=1
  local delay=2
  while true; do
    if gh "$@"; then
      return 0
    fi
    if [ "$attempt" -ge 3 ]; then
      echo "error: gh $* failed after $attempt attempts" >&2
      return 1
    fi
    echo "warning: gh $* failed; retrying in ${delay}s" >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

issue_number=""
issue_url=""
if [ "$DRY_RUN" = "1" ]; then
  mkdir -p "$(dirname "$STATE_FILE")"
  issue_number="${SUPERVISOR_PUBLISH_DRY_RUN_ISSUE:-999}"
  issue_url="https://github.com/${GH_REPO:-dry-run/repo}/issues/$issue_number"
  if [ -n "${SUPERVISOR_PUBLISH_LOG:-}" ]; then
    {
      echo "DRY_RUN issue_number=$issue_number"
      echo "DRY_RUN rank_changed=$rank_changed"
      echo "DRY_RUN body_file=$body_file"
    } >> "$SUPERVISOR_PUBLISH_LOG"
  fi
else
  issues_json="$tmpdir/issues.json"
  retry_gh issue list --repo "$GH_REPO" \
    --search "$TITLE in:title is:open" \
    --json number,title,url \
    > "$issues_json"
  matches="$(jq --arg title "$TITLE" '[.[] | select(.title == $title)]' "$issues_json")"
  match_count="$(jq 'length' <<< "$matches")"

  if [ "$match_count" -eq 0 ]; then
    issue_url="$(retry_gh issue create --repo "$GH_REPO" --title "$TITLE" --body-file "$body_file")"
    issue_number="${issue_url##*/}"
  elif [ "$match_count" -eq 1 ]; then
    issue_number="$(jq -r '.[0].number' <<< "$matches")"
    issue_url="$(jq -r '.[0].url' <<< "$matches")"
    retry_gh issue edit "$issue_number" --repo "$GH_REPO" --body-file "$body_file"
  else
    echo "error: duplicate supervisor-rank issues open: $(jq -r '.[].number' <<< "$matches" | paste -sd ',')" >&2
    exit 1
  fi

  if [ "$rank_changed" = "true" ]; then
    entered="$(jq -n --argjson prev "$previous_top" --argjson curr "$current_top" '$curr - $prev | join(", ")')"
    exited="$(jq -n --argjson prev "$previous_top" --argjson curr "$current_top" '$prev - $curr | join(", ")')"
    retry_gh issue comment "$issue_number" --repo "$GH_REPO" \
      --body "Rank order changed. Entered top-3: ${entered:-none}. Exited top-3: ${exited:-none}."
  fi
fi

jq -n \
  --arg last_run_at "$generated_at" \
  --argjson top_ids "$current_top" \
  --argjson rank_changed "$rank_changed" \
  --argjson run_number "$run_number" \
  --arg issue_number "$issue_number" \
  --arg issue_url "$issue_url" \
  --slurpfile ranked "$RANKED_JSON" \
  '{
    last_run_at: $last_run_at,
    last_run_top_ids: $top_ids,
    rank_changed: $rank_changed,
    run_number: $run_number,
    issue_number: (if $issue_number == "" then null else ($issue_number | tonumber) end),
    issue_url: (if $issue_url == "" then null else $issue_url end),
    stage_summary: ($ranked[0].stage_summary // {}),
    unknown_count: (($ranked[0].unknown // []) | length)
  }' > "$new_state"

mv "$new_state" "$STATE_FILE"
echo "supervisor-rank issue: ${issue_url:-dry-run}"
