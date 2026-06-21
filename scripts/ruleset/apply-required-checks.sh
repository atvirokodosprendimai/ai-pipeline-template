#!/usr/bin/env bash
# Set a repo ruleset's required status checks to exactly the given contexts
# (#1599 retarget U4: require the ci.yml job checks so the autobox's PRs gate on
# the same CI a human's do). CREATE-IF-ABSENT: appends a required_status_checks
# rule when the ruleset has none (today's state on both repos).
#
# SAFETY: dry-run by default (prints current → proposed, exits); --apply to PUT.
# Idempotent. Refuses to apply while any open bot PR is CONFLICTING (a missing
# required check dead-ends it). Edits the ruleset, not classic branch protection.
#
# Usage: REPO=owner/name RULESET_ID=123 CHECKS="a,b,c" apply-required-checks.sh [--apply]
set -euo pipefail

: "${REPO:?REPO=owner/name required}"
: "${RULESET_ID:?RULESET_ID required}"
: "${CHECKS:?CHECKS=comma,separated required}"
command -v jq >/dev/null || { echo "jq required"; exit 1; }

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

echo "Repo:    $REPO"
echo "Ruleset: $RULESET_ID"
echo "Require: $CHECKS"
echo

ruleset_json="$(gh api "repos/${REPO}/rulesets/${RULESET_ID}")"
echo "Current required checks:"
printf '%s' "$ruleset_json" | jq -r '
  (.rules[]? | select(.type=="required_status_checks")
   | .parameters.required_status_checks[]?.context) // empty' \
  | sed 's/^/  - /' || true
echo

conflicting="$(
  gh pr list --repo "$REPO" --state open --json number,headRefName,mergeable \
    --jq '[.[]|select(.headRefName|startswith("bot/"))|select(.mergeable=="CONFLICTING")|.number]|join(",")' \
    2>/dev/null || true)"
if [ -n "$conflicting" ]; then
  echo "REFUSING: open CONFLICTING bot PR(s): #${conflicting} — a new required check"
  echo "would be ABSENT on them and dead-end them. Drain (conflict-heal) first."
  exit 2
fi
echo "Drain gate: no open CONFLICTING bot PRs."
echo

# checks array from CHECKS; create-if-absent the required_status_checks rule.
checks_json="$(printf '%s' "$CHECKS" | jq -R 'split(",") | map({context: .})')"
new_ruleset="$(
  printf '%s' "$ruleset_json" | jq --argjson checks "$checks_json" '
    if ([.rules[]|select(.type=="required_status_checks")]|length) > 0
    then .rules |= map(if .type=="required_status_checks"
                       then .parameters.required_status_checks = $checks else . end)
    else .rules += [{type:"required_status_checks",
                     parameters:{strict_required_status_checks_policy:false,
                                 required_status_checks:$checks}}]
    end')"

echo "Proposed required checks:"
printf '%s' "$new_ruleset" | jq -r '
  .rules[]|select(.type=="required_status_checks")
  |.parameters.required_status_checks[].context' | sed 's/^/  - /'
echo

if [ "$APPLY" -ne 1 ]; then
  echo "DRY RUN — pass --apply to PUT. No changes made."
  exit 0
fi

printf '%s' "$new_ruleset" \
  | jq '{name, target, enforcement, bypass_actors, conditions, rules}' \
  | gh api -X PUT "repos/${REPO}/rulesets/${RULESET_ID}" --input -
echo "Applied."
