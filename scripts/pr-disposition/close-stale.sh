#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SANITISE="${PR_DISPOSITION_SANITISE:-${ROOT_DIR}/company/scripts/sanitise.sh}"
STATE_PATH="${PR_DISPOSITION_STATE:-${ROOT_DIR}/company/pr-disposition-state.json}"
PR_NUMBER="${1:?usage: close-stale.sh PR_NUMBER CLASSIFICATION_JSON}"
CLASSIFICATION_JSON="${2:?usage: close-stale.sh PR_NUMBER CLASSIFICATION_JSON}"

escalate() {
  local pr="$1"
  local reason="Stale-close reason failed sanitise; human review required."
  gh pr edit "$pr" --add-label needs-human || true
  gh pr comment "$pr" --body "$reason" || true
  echo "Escalated PR #${pr}: ${reason}"
}

if ! jq -e '.class == "stale" and (.reasons | type == "array")' <<< "$CLASSIFICATION_JSON" >/dev/null 2>&1; then
  echo "close-stale.sh requires a stale classification JSON" >&2
  exit 1
fi

reasons_text="$(jq -r '.reasons | map(select(type == "string" and length > 0)) | join("; ")' <<< "$CLASSIFICATION_JSON")"
if [[ -z "$reasons_text" ]]; then
  reasons_text="the classifier judged this PR superseded or no longer goal-aligned"
fi

reason="Closing this PR as stale because it no longer appears to move the repository toward STRATEGY.md: ${reasons_text}. This reasoned close reduces PR dwell while preserving the discussion for reopening if needed."

if ! safe_reason="$(printf '%s' "$reason" | "$SANITISE")"; then
  escalate "$PR_NUMBER"
  exit 0
fi

mkdir -p "$(dirname "$STATE_PATH")"
if [[ ! -f "$STATE_PATH" ]]; then
  printf '{"ledger":[],"acted_fingerprints":[]}\n' > "$STATE_PATH"
fi

tmp_state="$(mktemp)"
timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
risk_tier="$(jq -r '.risk_tier // "unknown"' <<< "$CLASSIFICATION_JSON")"
jq \
  --arg ts "$timestamp" \
  --arg pr "$PR_NUMBER" \
  --arg risk "$risk_tier" \
  --arg reason "$safe_reason" \
  --argjson reasons "$(jq '.reasons' <<< "$CLASSIFICATION_JSON")" \
  '.ledger = ((.ledger // []) + [{
    timestamp: $ts,
    pr_number: ($pr | tonumber),
    action: "close-stale",
    class: "stale",
    risk_tier: $risk,
    reasons: $reasons,
    reason: $reason
  }]) | .acted_fingerprints = (.acted_fingerprints // [])' \
  "$STATE_PATH" > "$tmp_state"

if ! "$SANITISE" < "$tmp_state" >/dev/null; then
  escalate "$PR_NUMBER"
  rm -f "$tmp_state"
  exit 0
fi

gh pr close "$PR_NUMBER" --comment "$safe_reason" --delete-branch
mv "$tmp_state" "$STATE_PATH"
