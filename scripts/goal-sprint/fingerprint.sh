#!/usr/bin/env bash
set -uo pipefail
trap 'status=$?; echo "WARN: fingerprint command failed near line $LINENO (status $status)" >&2; true' ERR

json="/tmp/goal_sprint.json"
sentinel="/tmp/goal-sprint-material-changed"
state_file="company/goal-sprint-state.json"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

keywords_from_slug() {
  printf '%s\n' "$1" |
    tr '[:upper:]' '[:lower:]' |
    tr '-' '\n' |
    tr -cs 'a-z0-9' '\n' |
    grep -v -E '^(the|a|an|in|on|for|to|of|and|or|is|set|add|configure|verify|check|update|review|approve|implement|basic|define|fix|enable|goal|sprint)$' |
    head -5 || true
}

[ -f "$json" ] || fail "$json not found"
command -v jq >/dev/null 2>&1 || fail "jq is required"

fingerprint="$(jq -r '.top.fingerprint // .fingerprint // ""' "$json")" || fail "failed to read fingerprint"
[ -n "$fingerprint" ] && [ "$fingerprint" != "null" ] || fail "fingerprint missing"

last=""
if [ -f "$state_file" ]; then
  last="$(jq -r '.last_fingerprint // ""' "$state_file" 2>/dev/null || true)"
fi

if [ "$fingerprint" = "$last" ]; then
  echo "false" > "$sentinel"
  echo "Material changed: false (fingerprint unchanged: $fingerprint)"
  exit 0
fi

seed_repo="${SEED_REPO:-}"
[ -n "$seed_repo" ] || fail "SEED_REPO is required"
command -v gh >/dev/null 2>&1 || fail "gh is required"

open_json="$(gh issue list --repo "$seed_repo" --label goal-sprint --state open --json title)" || fail "failed to list open goal-sprint issues"
open_titles="/tmp/goal-sprint-open-titles.txt"
printf '%s\n' "$open_json" | jq -r '.[].title // empty' > "$open_titles" || fail "failed to parse open issue titles"

keywords="$(keywords_from_slug "$fingerprint")"
match_count=0
while IFS= read -r existing_title; do
  existing_lower="$(printf '%s\n' "$existing_title" | tr '[:upper:]' '[:lower:]')"
  hits=0
  for kw in $keywords; do
    if printf '%s\n' "$existing_lower" | grep -q "$kw"; then
      hits=$((hits + 1))
    fi
  done
  if [ "$hits" -ge 2 ]; then
    match_count=$((match_count + 1))
    break
  fi
done < "$open_titles"

if [ "$match_count" = "0" ]; then
  echo "true" > "$sentinel"
  echo "Material changed: true (new fingerprint '$fingerprint', no matching open goal-sprint issue)"
else
  echo "false" > "$sentinel"
  echo "Material changed: false (new fingerprint '$fingerprint' matches an open goal-sprint issue)"
fi
