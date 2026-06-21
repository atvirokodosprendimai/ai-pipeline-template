#!/usr/bin/env bash
# #1599 Phase D — swap the protect-main ruleset's required status checks:
# ADD `ci/guards` (the single shared CI gate, posted by the box for bot PRs and
# by external-pr-ci.yml for external PRs) and REMOVE the three standalone
# workflow contexts (pipeline-ci / sanitise-wall / pii-policy-check) once the
# box + external producers are proven green.
#
# SAFETY:
#   * Dry-run by DEFAULT — prints the current and proposed required-check sets
#     and exits without mutating. Pass --apply to PUT the updated ruleset.
#   * Idempotent — re-running after a successful apply is a no-op (ci/guards
#     already present, the three already removed).
#   * Drain gate — refuses to apply while any OPEN bot PR is CONFLICTING: such a
#     PR fires no workflows / gets no box status, so a newly required `ci/guards`
#     would be ABSENT (not red) and the PR would dead-end. Conflict-heal (#1930)
#     drains these; this is the KTD5 precondition.
#
# Edits the repo RULESET (not classic branch protection) — the protect-main
# ruleset is the real gate. Requires `gh` (admin on the repo) and `jq`.
set -euo pipefail

REPO="${REPO:-atvirokodosprendimai/ai-pipeline-template}"
RULESET_ID="${RULESET_ID:-13925617}"
CI_GUARDS_CONTEXT="${CI_GUARDS_CONTEXT:-ci/guards}"
# Contexts retired by Phase D once ci/guards carries the guards on both paths.
REMOVE_JSON='["pipeline-ci","sanitise-wall","pii-policy-check"]'

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

command -v jq >/dev/null || { echo "jq is required"; exit 1; }

echo "Repo:    $REPO"
echo "Ruleset: $RULESET_ID (protect-main)"
echo "Add:     $CI_GUARDS_CONTEXT"
echo "Remove:  $REMOVE_JSON"
echo

ruleset_json="$(gh api "repos/${REPO}/rulesets/${RULESET_ID}")"

echo "Current required checks:"
printf '%s' "$ruleset_json" | jq -r '
  (.rules[] | select(.type=="required_status_checks")
   | .parameters.required_status_checks[].context)
  // empty' | sed 's/^/  - /' || echo "  (none / unreadable)"
echo

# Drain gate: any OPEN bot PR that is CONFLICTING blocks the swap.
conflicting="$(
  gh pr list --repo "$REPO" --state open --json number,headRefName,mergeable \
    --jq '[.[] | select(.headRefName|startswith("bot/")) | select(.mergeable=="CONFLICTING") | .number] | join(",")' \
    2>/dev/null || true
)"
if [ -n "$conflicting" ]; then
  echo "REFUSING: open CONFLICTING bot PR(s): #${conflicting}."
  echo "A required ci/guards would be ABSENT on these and dead-end them."
  echo "Let conflict-heal (#1930) rebase them to zero first (KTD5), then re-run."
  exit 2
fi
echo "Drain gate: no open CONFLICTING bot PRs."
echo

# New ruleset with the required_status_checks list swapped (every other rule,
# parameter, condition, and bypass actor preserved verbatim).
new_ruleset="$(
  printf '%s' "$ruleset_json" | jq \
    --arg add "$CI_GUARDS_CONTEXT" \
    --argjson remove "$REMOVE_JSON" '
    .rules |= map(
      if .type=="required_status_checks" then
        .parameters.required_status_checks =
          ( ( [.parameters.required_status_checks[]
               | select(.context as $c | ($remove | index($c)) | not)]
              + [{context:$add, integration_id:null}] )
            | unique_by(.context) )
      else . end
    )
  '
)"

echo "New required checks:"
printf '%s' "$new_ruleset" | jq -r '
  .rules[] | select(.type=="required_status_checks")
  | .parameters.required_status_checks[].context' | sed 's/^/  - /'
echo

if [ "$APPLY" -ne 1 ]; then
  echo "DRY RUN — pass --apply to PUT the ruleset. No changes made."
  exit 0
fi

# PUT the full ruleset back (name/target/enforcement/conditions/bypass_actors
# preserved from the fetched object; only rules changed).
printf '%s' "$new_ruleset" \
  | jq '{name, target, enforcement, bypass_actors, conditions, rules}' \
  | gh api -X PUT "repos/${REPO}/rulesets/${RULESET_ID}" --input -

echo
echo "Applied. Verify:"
echo "  gh api repos/${REPO}/rulesets/${RULESET_ID} --jq '.rules[]|select(.type==\"required_status_checks\").parameters.required_status_checks[].context'"
