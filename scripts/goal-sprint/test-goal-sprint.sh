#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOTAL=7
PASSED=0

pass() {
  PASSED=$((PASSED + 1))
  echo "PASS: $1"
}

fail() {
  echo "FAIL: $1 — $2"
}

make_workspace() {
  local work
  work="$(mktemp -d)"
  mkdir -p "$work/scripts/goal-sprint" "$work/company" "$work/docs/pulse-reports"
  cp "$SCRIPT_DIR/build-context.sh" "$work/scripts/goal-sprint/build-context.sh"
  cp "$SCRIPT_DIR/fingerprint.sh" "$work/scripts/goal-sprint/fingerprint.sh"
  cp "$SCRIPT_DIR/emit.sh" "$work/scripts/goal-sprint/emit.sh"
  chmod +x "$work/scripts/goal-sprint/"*.sh
  printf '%s\n' "$work"
}

write_goal_json() {
  local path="$1"
  local class="$2"
  local title="$3"
  local fingerprint="$4"
  cat > "$path" <<EOF_JSON
{
  "ideas": [
    {"title": "One", "rationale": "Moves a metric", "impact": "high", "effort": "low", "metric": "autonomous_ship_rate"},
    {"title": "Two", "rationale": "Moves a metric", "impact": "medium", "effort": "low", "metric": "spec_coverage"},
    {"title": "Three", "rationale": "Moves a metric", "impact": "medium", "effort": "medium", "metric": "active_stuck_issues"},
    {"title": "Four", "rationale": "Moves a metric", "impact": "low", "effort": "low", "metric": "pr_processing_rate"},
    {"title": "Five", "rationale": "Moves a metric", "impact": "high", "effort": "medium", "metric": "lead_time_hours"}
  ],
  "top": {
    "title": "$title",
    "problem": "A concrete test problem.",
    "acceptance_criteria": ["First criterion", "Second criterion"],
    "build_sequence": ["First step", "Second step"],
    "class": "$class",
    "labels": ["goal-sprint"]
  },
  "fingerprint": "$fingerprint"
}
EOF_JSON
}

install_gh_mock() {
  local bin_dir="$1"
  mkdir -p "$bin_dir"
  cat > "$bin_dir/gh" <<'EOF_GH'
#!/usr/bin/env bash
echo "$*" >> /tmp/gh-mock-calls.log
if [ "${1:-}" = "issue" ] && [ "${2:-}" = "list" ]; then
  printf '[]\n'
  exit 0
fi
if [ "${1:-}" = "issue" ] && [ "${2:-}" = "create" ]; then
  i=1
  while [ "$i" -le "$#" ]; do
    eval "arg=\${$i}"
    if [ "$arg" = "--body-file" ]; then
      next=$((i + 1))
      eval "body_file=\${$next}"
      {
        echo "BODY_BEGIN"
        cat "$body_file"
        echo "BODY_END"
      } >> /tmp/gh-mock-calls.log
    fi
    i=$((i + 1))
  done
  printf 'https://github.com/example/repo/issues/123\n'
  exit 0
fi
exit 0
EOF_GH
  chmod +x "$bin_dir/gh"
}

reset_mock_log() {
  : > /tmp/gh-mock-calls.log
}

scenario_1() {
  local desc="fingerprint.sh new idea writes true sentinel"
  local work mock rc
  work="$(make_workspace)"
  mock="$work/mock-bin"
  install_gh_mock "$mock"
  printf '{ "last_fingerprint": "old-idea", "last_week": "", "ledger": [], "last_issue": null }\n' > "$work/company/goal-sprint-state.json"
  write_goal_json /tmp/goal_sprint.json automatable "Ship Real Metric" "ship-real-metric"
  reset_mock_log
  (cd "$work" && PATH="$mock:$PATH" SEED_REPO=example/repo scripts/goal-sprint/fingerprint.sh >/tmp/scenario1.out 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ] && [ "$(cat /tmp/goal-sprint-material-changed)" = "true" ]; then
    pass "$desc"
  else
    fail "$desc" "$(cat /tmp/scenario1.out)"
  fi
}

scenario_2() {
  local desc="fingerprint.sh same idea writes false sentinel"
  local work mock rc
  work="$(make_workspace)"
  mock="$work/mock-bin"
  install_gh_mock "$mock"
  printf '{ "last_fingerprint": "ship-real-metric", "last_week": "", "ledger": [], "last_issue": null }\n' > "$work/company/goal-sprint-state.json"
  write_goal_json /tmp/goal_sprint.json automatable "Ship Real Metric" "ship-real-metric"
  reset_mock_log
  (cd "$work" && PATH="$mock:$PATH" SEED_REPO=example/repo scripts/goal-sprint/fingerprint.sh >/tmp/scenario2.out 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ] && [ "$(cat /tmp/goal-sprint-material-changed)" = "false" ]; then
    pass "$desc"
  else
    fail "$desc" "$(cat /tmp/scenario2.out)"
  fi
}

scenario_3() {
  local desc="emit.sh automatable creates one issue with goal-sprint and needs-triage labels"
  local work mock creates rc
  work="$(make_workspace)"
  mock="$work/mock-bin"
  install_gh_mock "$mock"
  printf '{ "last_fingerprint": "", "last_week": "", "ledger": [], "last_issue": null }\n' > "$work/company/goal-sprint-state.json"
  write_goal_json /tmp/goal_sprint.json automatable "Ship Real Metric" "ship-real-metric"
  echo true > /tmp/goal-sprint-material-changed
  reset_mock_log
  (cd "$work" && PATH="$mock:$PATH" SEED_REPO=example/repo scripts/goal-sprint/emit.sh >/tmp/scenario3.out 2>&1)
  rc=$?
  creates="$(grep -c '^issue create ' /tmp/gh-mock-calls.log || true)"
  if [ "$rc" -eq 0 ] && [ "$creates" = "1" ] && grep -q -- '--label goal-sprint,needs-triage' /tmp/gh-mock-calls.log && ! grep -q 'needs-human' /tmp/gh-mock-calls.log; then
    pass "$desc"
  else
    fail "$desc" "$(cat /tmp/scenario3.out) $(cat /tmp/gh-mock-calls.log)"
  fi
}

scenario_4() {
  local desc="emit.sh duplicate fingerprint creates zero issues"
  local work mock creates rc
  work="$(make_workspace)"
  mock="$work/mock-bin"
  install_gh_mock "$mock"
  printf '{ "last_fingerprint": "ship-real-metric", "last_week": "", "ledger": [], "last_issue": null }\n' > "$work/company/goal-sprint-state.json"
  write_goal_json /tmp/goal_sprint.json automatable "Ship Real Metric" "ship-real-metric"
  echo true > /tmp/goal-sprint-material-changed
  reset_mock_log
  (cd "$work" && PATH="$mock:$PATH" SEED_REPO=example/repo scripts/goal-sprint/emit.sh >/tmp/scenario4.out 2>&1)
  rc=$?
  creates="$(grep -c '^issue create ' /tmp/gh-mock-calls.log || true)"
  if [ "$rc" -eq 0 ] && [ "$creates" = "0" ]; then
    pass "$desc"
  else
    fail "$desc" "$(cat /tmp/scenario4.out) $(cat /tmp/gh-mock-calls.log)"
  fi
}

scenario_5() {
  local desc="emit.sh needs-human labels and body escalation note"
  local work mock rc
  work="$(make_workspace)"
  mock="$work/mock-bin"
  install_gh_mock "$mock"
  printf '{ "last_fingerprint": "", "last_week": "", "ledger": [], "last_issue": null }\n' > "$work/company/goal-sprint-state.json"
  write_goal_json /tmp/goal_sprint.json needs-human "Call Buyers This Week" "call-buyers-this-week"
  echo true > /tmp/goal-sprint-material-changed
  reset_mock_log
  (cd "$work" && PATH="$mock:$PATH" SEED_REPO=example/repo scripts/goal-sprint/emit.sh >/tmp/scenario5.out 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ] && grep -q -- '--label goal-sprint,needs-human' /tmp/gh-mock-calls.log && grep -q 'Autonomy ladder: attempt via pipeline -> Codex -> RAH bounty -> operator.' /tmp/gh-mock-calls.log; then
    pass "$desc"
  else
    fail "$desc" "$(cat /tmp/scenario5.out) $(cat /tmp/gh-mock-calls.log)"
  fi
}

scenario_6() {
  local desc="build-context.sh with all files present writes non-empty context containing STRATEGY.md content"
  local work rc
  work="$(make_workspace)"
  echo "North Star Strategy Content" > "$work/STRATEGY.md"
  echo "Pulse Report Content" > "$work/docs/pulse-reports/2026-06-05_20-30.md"
  echo '{"status":"ok"}' > "$work/company/loop-state.json"
  echo '{"last_fingerprint":"previous-bet"}' > "$work/company/goal-sprint-state.json"
  (cd "$work" && scripts/goal-sprint/build-context.sh >/tmp/scenario6.out 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ] && [ -s /tmp/goal_sprint_user.txt ] && grep -q 'North Star Strategy Content' /tmp/goal_sprint_user.txt; then
    pass "$desc"
  else
    fail "$desc" "$(cat /tmp/scenario6.out)"
  fi
}

scenario_7() {
  local desc="build-context.sh with optional files absent exits zero and writes non-empty context"
  local work rc
  work="$(make_workspace)"
  (cd "$work" && scripts/goal-sprint/build-context.sh >/tmp/scenario7.out 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ] && [ -s /tmp/goal_sprint_user.txt ]; then
    pass "$desc"
  else
    fail "$desc" "$(cat /tmp/scenario7.out)"
  fi
}

scenario_1
scenario_2
scenario_3
scenario_4
scenario_5
scenario_6
scenario_7

if [ "$PASSED" -eq "$TOTAL" ]; then
  echo "PASS $PASSED/$TOTAL"
  exit 0
fi

echo "FAIL $((TOTAL - PASSED))/$TOTAL"
exit 1
