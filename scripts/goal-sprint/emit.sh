#!/usr/bin/env bash
set -uo pipefail
trap 'status=$?; echo "WARN: emit command failed near line $LINENO (status $status)" >&2; true' ERR

json="/tmp/goal_sprint.json"
sentinel="/tmp/goal-sprint-material-changed"
state_file="company/goal-sprint-state.json"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

keywords_from_title() {
  printf '%s\n' "$1" |
    tr '[:upper:]' '[:lower:]' |
    tr -cs 'a-z0-9' '\n' |
    grep -v -E '^(the|a|an|in|on|for|to|of|and|or|is|set|add|configure|verify|check|update|review|approve|implement|basic|define|fix|enable|goal|sprint)$' |
    head -5 || true
}

normalise_title() {
  printf '%s\n' "$1" |
    tr '[:upper:]' '[:lower:]' |
    sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/[[:space:]]+/ /g'
}

script_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -n "${GITHUB_WORKSPACE:-}" ]; then
  repo_root="$GITHUB_WORKSPACE"
else
  repo_root="$(git -C "$script_dir" rev-parse --show-toplevel)" || fail "failed to resolve repo root"
fi
SANITISE="$repo_root/company/scripts/sanitise.sh"
[ -f "$SANITISE" ] || fail "$SANITISE not found"

[ -f "$sentinel" ] || fail "$sentinel not found"
if [ "$(cat "$sentinel")" != "true" ]; then
  echo "SKIP: material change sentinel is not true"
  exit 0
fi

[ -f "$json" ] || fail "$json not found"
command -v jq >/dev/null 2>&1 || fail "jq is required"

seed_repo="${SEED_REPO:-}"
[ -n "$seed_repo" ] || fail "SEED_REPO is required"
command -v gh >/dev/null 2>&1 || fail "gh is required"

fingerprint="$(jq -r '.top.fingerprint // .fingerprint // ""' "$json")" || fail "failed to read fingerprint"
title="$(jq -r '.top.title // ""' "$json")" || fail "failed to read top.title"
problem="$(jq -r '.top.problem // ""' "$json")" || fail "failed to read top.problem"
class="$(jq -r '.top.class // ""' "$json")" || fail "failed to read top.class"

[ -n "$fingerprint" ] && [ "$fingerprint" != "null" ] || fail "fingerprint missing"
[ -n "$title" ] && [ "$title" != "null" ] || fail "top.title missing"
[ "$class" = "automatable" ] || [ "$class" = "needs-human" ] || fail "top.class must be automatable or needs-human"

last=""
if [ -f "$state_file" ]; then
  last="$(jq -r '.last_fingerprint // ""' "$state_file" 2>/dev/null || true)"
fi
if [ "$fingerprint" = "$last" ]; then
  echo "SKIP: duplicate detected"
  exit 0
fi

issue_json="$(gh issue list --repo "$seed_repo" --state all --limit 200 --json title)" || fail "failed to list seed repo issues"
all_titles="/tmp/goal-sprint-all-titles.txt"
printf '%s\n' "$issue_json" | jq -r '.[].title // empty' > "$all_titles" || fail "failed to parse seed repo issue titles"

keywords="$(keywords_from_title "$title")"
title_exact="$(normalise_title "$title")"
match_count=0
while IFS= read -r existing_title; do
  if [ -z "$keywords" ]; then
    if [ "$(normalise_title "$existing_title")" = "$title_exact" ]; then
      match_count=$((match_count + 1))
      break
    fi
    continue
  fi
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
done < "$all_titles"

if [ "$match_count" != "0" ]; then
  echo "SKIP: duplicate detected"
  exit 0
fi

body_file="/tmp/goal-sprint-issue-body.md"
{
  echo "## Problem"
  echo ""
  echo "$problem"
  echo ""
  echo "## Acceptance Criteria"
  jq -r '.top.acceptance_criteria[]? | "- " + .' "$json" || fail "failed to read acceptance criteria"
  echo ""
  echo "## Build Sequence"
  jq -r '.top.build_sequence[]? | "- " + .' "$json" || fail "failed to read build sequence"
  if [ "$class" = "needs-human" ]; then
    echo ""
    echo "## Escalation"
    echo ""
    echo "Autonomy ladder: attempt via pipeline -> Codex -> RAH bounty -> operator."
  fi
} > "$body_file"

labels="goal-sprint"
if [ "$class" = "automatable" ]; then
  labels="${labels},needs-triage"
else
  labels="${labels},needs-human"
fi

BODY="$(cat "$body_file")"
if ! printf '%s' "$title $BODY" | bash "$SANITISE" > /dev/null 2>&1; then
  echo "::error:: sanitise.sh rejected issue content"
  exit 1
fi

issue_url="$(gh issue create --repo "$seed_repo" --title "$title" --body-file "$body_file" --label "$labels")" || fail "failed to create goal-sprint issue"
issue_number="$(printf '%s\n' "$issue_url" | grep -Eo '/issues/[0-9]+' | tail -1 | tr -cd '0-9' || true)"

if [ ! -f "$state_file" ]; then
  mkdir -p "$(dirname "$state_file")"
  printf '{ "last_fingerprint": "", "last_week": "", "ledger": [], "last_issue": null }\n' > "$state_file"
fi

week="$(date -u '+%G-W%V')"
entry="$(jq -n \
  --arg week "$week" \
  --arg fingerprint "$fingerprint" \
  --arg title "$title" \
  --arg class "$class" \
  --arg issue_url "$issue_url" \
  --arg issue_number "$issue_number" \
  --argjson ideas "$(jq '.ideas' "$json")" \
  '{
    week: $week,
    fingerprint: $fingerprint,
    title: $title,
    class: $class,
    ideas: $ideas,
    issue: {
      number: (if $issue_number == "" then null else ($issue_number | tonumber) end),
      url: $issue_url
    }
  }')" || fail "failed to build ledger entry"

jq \
  --arg fingerprint "$fingerprint" \
  --arg week "$week" \
  --arg issue_url "$issue_url" \
  --arg issue_number "$issue_number" \
  --argjson entry "$entry" \
  '.last_fingerprint = $fingerprint
   | .last_week = $week
   | .ledger = ((.ledger // []) + [$entry])
   | .last_issue = {
       number: (if $issue_number == "" then null else ($issue_number | tonumber) end),
       url: $issue_url
     }' "$state_file" > /tmp/goal-sprint-state.json || fail "failed to update goal sprint state"
mv /tmp/goal-sprint-state.json "$state_file" || fail "failed to write $state_file"

echo "Created goal-sprint issue: ${issue_url:-unknown}"
