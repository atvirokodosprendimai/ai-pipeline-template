#!/usr/bin/env bash
set -euo pipefail

# Reads env: PR_NUMBER, PR_TITLE, PR_BODY, ISSUE_NUMBER (may be empty), FILES (newline list), MERGED_AT
# Appends ONE JSONL line to $1 (default: compound-queue.jsonl)
# Uses jq -c -n with --arg/--argjson -- NEVER string-concat JSON
# Keys: pr (number), title, issue (number or null), body_excerpt (first 800 chars of body), files (array), merged_at
# No network. No secrets in output.

out_path="${1:-compound-queue.jsonl}"

: "${PR_NUMBER:?PR_NUMBER is required}"
: "${PR_TITLE:?PR_TITLE is required}"
: "${MERGED_AT:?MERGED_AT is required}"

pr_body="${PR_BODY:-}"
issue_number="${ISSUE_NUMBER:-}"
files="${FILES:-}"
body_excerpt="${pr_body:0:800}"

files_json="$(printf '%s' "$files" | jq -R -s 'split("\n") | map(select(length > 0))')"

if [[ -n "$issue_number" ]]; then
  issue_json="$issue_number"
else
  issue_json="null"
fi

jq -c -n \
  --argjson pr "$PR_NUMBER" \
  --arg title "$PR_TITLE" \
  --argjson issue "$issue_json" \
  --arg body_excerpt "$body_excerpt" \
  --argjson files "$files_json" \
  --arg merged_at "$MERGED_AT" \
  '{
    pr: $pr,
    title: $title,
    issue: $issue,
    body_excerpt: $body_excerpt,
    files: $files,
    merged_at: $merged_at
  }' >> "$out_path"
