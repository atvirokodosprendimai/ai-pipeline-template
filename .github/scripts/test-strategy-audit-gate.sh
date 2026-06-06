#!/usr/bin/env bash
set -euo pipefail

source .github/scripts/strategy-audit-gate.sh

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

fail() {
  echo "FAIL test-strategy-audit-gate: $1" >&2
  exit 1
}

write_metric_rows() {
  local output="$1"
  shift
  jq -n '$ARGS.positional | map({key: ., verdict: "DRIFT", drift: true})' --args "$@" > "$output"
}

write_ok_rows() {
  local output="$1"
  jq -n '[{key:"paid_customers", verdict:"OK", drift:false}]' > "$output"
}

write_milestones() {
  local output="$1"
  shift
  jq -n '$ARGS.positional | map({date: ., status: "overdue"})' --args "$@" > "$output"
}

write_ok_milestones() {
  local output="$1"
  jq -n '[{date:"2026-05-31", status:"met"}]' > "$output"
}

write_baseline() {
  local output="$1"
  local fingerprint="$2"
  local paid_customers="$3"
  local ran_at="$4"

  jq -n \
    --arg fp "$fingerprint" \
    --arg ran_at "$ran_at" \
    --argjson paid "$paid_customers" '
      {
        last_reported_drift_fingerprint: $fp,
        audits: [{
          ran_at: $ran_at,
          metrics: {
            paid_customers: $paid,
            autonomous_ship_rate: null,
            lead_time_hours: 5,
            self_heal_rate: 0,
            active_stuck_issues: 0,
            cycle_time_to_revenue: null,
            fetch_status: {paid_customers: "ok", cycle_time_to_revenue: "no_customers"}
          },
          milestones_status: []
        }]
      }
    ' > "$output"
}

append_candidate() {
  local baseline="$1"
  local output="$2"
  local paid_customers="$3"
  local ran_at="$4"

  jq \
    --arg ran_at "$ran_at" \
    --argjson paid "$paid_customers" '
      .audits = (
        ((.audits // []) + [{
          ran_at: $ran_at,
          metrics: {
            paid_customers: $paid,
            autonomous_ship_rate: null,
            lead_time_hours: 5,
            self_heal_rate: 0,
            active_stuck_issues: 0,
            cycle_time_to_revenue: null,
            fetch_status: {paid_customers: "ok", cycle_time_to_revenue: "no_customers"}
          },
          milestones_status: []
        }]) | .[-365:]
      )
    ' "$baseline" > "$output"
}

source_decision() {
  local decision_file="$1"
  # shellcheck disable=SC1090
  source "$decision_file"
}

# Scenario A: new drift fingerprint -> marker baseline is persisted and drift PR opens.
rows_drift="$tmpdir/rows-drift.json"
milestones_drift="$tmpdir/milestones-drift.json"
write_metric_rows "$rows_drift" paid_customers
write_milestones "$milestones_drift" 2026-05-31
fp_one="$(strategy_audit_drift_fingerprint "$rows_drift" "$milestones_drift" false)"

baseline_first="$tmpdir/baseline-first.json"
candidate_first="$tmpdir/candidate-first.json"
final_first="$tmpdir/final-first.json"
decision_first="$tmpdir/decision-first.env"
write_baseline "$baseline_first" "" 0 "2026-06-01T00:00:00Z"
append_candidate "$baseline_first" "$candidate_first" 0 "2026-06-02T00:00:00Z"
strategy_audit_decide "$baseline_first" "$candidate_first" true "$fp_one" "$final_first" "$decision_first"
source_decision "$decision_first"
[ "$STRATEGY_AUDIT_ACTION" = "open_pr" ] || fail "first drift run should open PR"
[ "$STRATEGY_AUDIT_OPEN_PR" = "true" ] || fail "first drift run should set open_pr=true"

marker_first="$tmpdir/marker-first.json"
strategy_audit_reported_fingerprint_baseline "$baseline_first" "$fp_one" "$marker_first"
[ "$(jq -r '.last_reported_drift_fingerprint' "$marker_first")" = "$fp_one" ] || fail "new drift should persist fingerprint to marker baseline"
jq -e --slurpfile baseline "$baseline_first" '.audits == $baseline[0].audits' "$marker_first" >/dev/null || fail "marker baseline should only update reported fingerprint"

# Scenario B: same drift fingerprint after marker baseline update -> no PR.
candidate_second="$tmpdir/candidate-second.json"
final_second="$tmpdir/final-second.json"
decision_second="$tmpdir/decision-second.env"
append_candidate "$marker_first" "$candidate_second" 0 "2026-06-03T00:00:00Z"
strategy_audit_decide "$marker_first" "$candidate_second" true "$fp_one" "$final_second" "$decision_second"
source_decision "$decision_second"
[ "$STRATEGY_AUDIT_ACTION" = "skip" ] || fail "second same drift should skip"
[ "$STRATEGY_AUDIT_OPEN_PR" = "false" ] || fail "second same drift should not open PR"

# Scenario C: changed drift fingerprint -> opens PR.
rows_changed="$tmpdir/rows-changed.json"
write_metric_rows "$rows_changed" active_stuck_issues paid_customers
fp_changed="$(strategy_audit_drift_fingerprint "$rows_changed" "$milestones_drift" false)"
[ "$fp_changed" != "$fp_one" ] || fail "changed fixture should produce a different fingerprint"

candidate_changed="$tmpdir/candidate-changed.json"
final_changed="$tmpdir/final-changed.json"
decision_changed="$tmpdir/decision-changed.env"
append_candidate "$final_first" "$candidate_changed" 0 "2026-06-04T00:00:00Z"
strategy_audit_decide "$final_first" "$candidate_changed" true "$fp_changed" "$final_changed" "$decision_changed"
source_decision "$decision_changed"
[ "$STRATEGY_AUDIT_ACTION" = "open_pr" ] || fail "changed drift should open PR"
[ "$STRATEGY_AUDIT_OPEN_PR" = "true" ] || fail "changed drift should set open_pr=true"

# Scenario D: no drift + timestamp-only change -> no commit and no PR.
rows_ok="$tmpdir/rows-ok.json"
milestones_ok="$tmpdir/milestones-ok.json"
write_ok_rows "$rows_ok"
write_ok_milestones "$milestones_ok"
fp_ok="$(strategy_audit_drift_fingerprint "$rows_ok" "$milestones_ok" false)"

baseline_ok="$tmpdir/baseline-ok.json"
candidate_timestamp="$tmpdir/candidate-timestamp.json"
final_timestamp="$tmpdir/final-timestamp.json"
decision_timestamp="$tmpdir/decision-timestamp.env"
write_baseline "$baseline_ok" "$fp_one" 0 "2026-06-01T00:00:00Z"
append_candidate "$baseline_ok" "$candidate_timestamp" 0 "2026-06-02T00:00:00Z"
strategy_audit_decide "$baseline_ok" "$candidate_timestamp" false "$fp_ok" "$final_timestamp" "$decision_timestamp"
source_decision "$decision_timestamp"
[ "$STRATEGY_AUDIT_ACTION" = "skip" ] || fail "timestamp-only no-drift run should skip"
[ "$STRATEGY_AUDIT_OPEN_PR" = "false" ] || fail "timestamp-only no-drift run should not open PR"
[ "$STRATEGY_AUDIT_COMMIT_MAIN" = "false" ] || fail "timestamp-only no-drift run should not commit"

# Scenario E: no drift + metric-value change -> commit to main, no PR.
candidate_metric="$tmpdir/candidate-metric.json"
final_metric="$tmpdir/final-metric.json"
decision_metric="$tmpdir/decision-metric.env"
append_candidate "$baseline_ok" "$candidate_metric" 1 "2026-06-02T00:00:00Z"
strategy_audit_decide "$baseline_ok" "$candidate_metric" false "$fp_ok" "$final_metric" "$decision_metric"
source_decision "$decision_metric"
[ "$STRATEGY_AUDIT_ACTION" = "commit_main" ] || fail "metric-value no-drift run should commit to main"
[ "$STRATEGY_AUDIT_OPEN_PR" = "false" ] || fail "metric-value no-drift run should not open PR"
[ "$STRATEGY_AUDIT_COMMIT_MAIN" = "true" ] || fail "metric-value no-drift run should set commit_main=true"

echo "PASS test-strategy-audit-gate: 5 scenarios"
