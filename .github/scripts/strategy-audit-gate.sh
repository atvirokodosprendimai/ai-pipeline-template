#!/usr/bin/env bash
set -euo pipefail

strategy_audit_drift_fingerprint() {
  local metric_rows_file="${1:?Usage: strategy_audit_drift_fingerprint <metric-rows-json> <milestones-json> [first-run]}"
  local milestones_file="${2:?Usage: strategy_audit_drift_fingerprint <metric-rows-json> <milestones-json> [first-run]}"
  local first_run="${3:-false}"

  if [ "$first_run" = "true" ]; then
    printf 'metrics=;overdue_milestones=\n'
    return 0
  fi

  jq -rn \
    --slurpfile rows "$metric_rows_file" \
    --slurpfile milestones "$milestones_file" '
      ($rows[0] // []) as $rows |
      ($milestones[0] // []) as $milestones |
      ($rows | map(select((.verdict // "") == "DRIFT" or (.drift // false) == true) | .key) | unique | sort) as $metric_keys |
      ($milestones | map(select(.status == "overdue") | .date) | unique | sort) as $overdue_dates |
      "metrics=" + ($metric_keys | join(",")) + ";overdue_milestones=" + ($overdue_dates | join(","))
    '
}

strategy_audit_metric_values_changed() {
  local baseline_file="${1:?Usage: strategy_audit_metric_values_changed <baseline-json> <candidate-json>}"
  local candidate_file="${2:?Usage: strategy_audit_metric_values_changed <baseline-json> <candidate-json>}"

  jq -e -n \
    --slurpfile baseline "$baseline_file" \
    --slurpfile candidate "$candidate_file" '
      def metric_values($state):
        (($state.audits[-1]? // {}) | (.metrics // {}) | del(.fetch_status));
      metric_values($baseline[0] // {}) != metric_values($candidate[0] // {})
    ' >/dev/null
}

strategy_audit_decide() {
  local baseline_file="${1:?Usage: strategy_audit_decide <baseline-json> <candidate-json> <any-drift> <fingerprint> <output-json> <decision-env>}"
  local candidate_file="${2:?Usage: strategy_audit_decide <baseline-json> <candidate-json> <any-drift> <fingerprint> <output-json> <decision-env>}"
  local any_drift="${3:?Usage: strategy_audit_decide <baseline-json> <candidate-json> <any-drift> <fingerprint> <output-json> <decision-env>}"
  local fingerprint="${4:?Usage: strategy_audit_decide <baseline-json> <candidate-json> <any-drift> <fingerprint> <output-json> <decision-env>}"
  local output_file="${5:?Usage: strategy_audit_decide <baseline-json> <candidate-json> <any-drift> <fingerprint> <output-json> <decision-env>}"
  local decision_file="${6:?Usage: strategy_audit_decide <baseline-json> <candidate-json> <any-drift> <fingerprint> <output-json> <decision-env>}"

  local last_reported
  last_reported="$(jq -r '.last_reported_drift_fingerprint // ""' "$baseline_file")"

  local metric_values_changed="false"
  if strategy_audit_metric_values_changed "$baseline_file" "$candidate_file"; then
    metric_values_changed="true"
  fi

  local action="skip"
  local open_pr="false"
  local commit_main="false"
  local output_fingerprint="$last_reported"

  if [ "$any_drift" = "true" ] && [ "$fingerprint" != "$last_reported" ]; then
    action="open_pr"
    open_pr="true"
    output_fingerprint="$fingerprint"
  elif [ "$metric_values_changed" = "true" ]; then
    action="commit_main"
    commit_main="true"
  fi

  jq --arg fp "$output_fingerprint" '.last_reported_drift_fingerprint = $fp' "$candidate_file" > "$output_file"

  {
    printf 'STRATEGY_AUDIT_ACTION=%s\n' "$action"
    printf 'STRATEGY_AUDIT_OPEN_PR=%s\n' "$open_pr"
    printf 'STRATEGY_AUDIT_COMMIT_MAIN=%s\n' "$commit_main"
    printf 'STRATEGY_AUDIT_METRIC_VALUES_CHANGED=%s\n' "$metric_values_changed"
    printf 'STRATEGY_AUDIT_DRIFT_FINGERPRINT=%q\n' "$fingerprint"
    printf 'STRATEGY_AUDIT_LAST_REPORTED_FINGERPRINT=%q\n' "$last_reported"
  } > "$decision_file"
}
