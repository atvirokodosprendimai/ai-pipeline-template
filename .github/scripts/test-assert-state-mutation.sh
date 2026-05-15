#!/usr/bin/env bash

script=".github/scripts/assert-state-mutation.sh"
tmpdirs=""

cleanup() {
  for dir in $tmpdirs; do
    if [ -n "$dir" ] && [ -d "$dir" ]; then
      rm -rf "$dir"
    fi
  done
}
trap cleanup EXIT

fail() {
  echo "FAIL test-assert-state-mutation: $1" >&2
  exit 1
}

make_tmpdir() {
  local dir
  dir="$(mktemp -d)" || return 1
  tmpdirs="${tmpdirs} ${dir}"
  printf '%s\n' "$dir"
}

create_state() {
  local path="$1"
  local last_check="$2"
  local count="$3"

  jq -n \
    --arg last_check "$last_check" \
    --argjson count "$count" \
    '{last_check: $last_check, consecutive_no_mutation_runs: $count}' > "$path"
}

run_assert() {
  local pre="$1"
  local state="$2"
  local log="$3"
  local out="$4"
  local err="$5"

  SUPERVISOR_ASSERT_DRY_RUN=1 \
    SUPERVISOR_ASSERT_LOG="$log" \
    GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
    bash "$script" "$pre" "$state" > "$out" 2> "$err"
}

line_count() {
  local pattern="$1"
  local file="$2"

  if [ ! -f "$file" ]; then
    printf '0\n'
    return 0
  fi
  grep -c "$pattern" "$file"
}

scenario_happy() {
  local scenario="happy"
  local dir state log out err status
  dir="$(make_tmpdir)" || fail "$scenario"
  state="$dir/state.json"
  log="$dir/assert.log"
  out="$dir/out"
  err="$dir/err"
  create_state "$state" "2026-05-15" 3 || fail "$scenario"

  run_assert "2026-05-10" "$state" "$log" "$out" "$err"
  status=$?

  [ "$status" -eq 0 ] || fail "$scenario"
  jq -e '.consecutive_no_mutation_runs == 0' "$state" >/dev/null || fail "$scenario"
  [ ! -s "$log" ] || fail "$scenario"
}

scenario_failure_1() {
  local scenario="failure-1"
  local dir state log out err status
  dir="$(make_tmpdir)" || fail "$scenario"
  state="$dir/state.json"
  log="$dir/assert.log"
  out="$dir/out"
  err="$dir/err"
  create_state "$state" "2026-05-10" 0 || fail "$scenario"

  run_assert "2026-05-10" "$state" "$log" "$out" "$err"
  status=$?

  [ "$status" -eq 1 ] || fail "$scenario"
  jq -e '.consecutive_no_mutation_runs == 1' "$state" >/dev/null || fail "$scenario"
  [ "$(line_count '^CREATE supervisor-dead ' "$log")" -eq 0 ] || fail "$scenario"
  [ "$(line_count '^COMMENT supervisor-dead ' "$log")" -eq 0 ] || fail "$scenario"
}

scenario_failure_2() {
  local scenario="failure-2"
  local dir state log out err status
  dir="$(make_tmpdir)" || fail "$scenario"
  state="$dir/state.json"
  log="$dir/assert.log"
  out="$dir/out"
  err="$dir/err"
  create_state "$state" "2026-05-10" 1 || fail "$scenario"

  run_assert "2026-05-10" "$state" "$log" "$out" "$err"
  status=$?

  [ "$status" -eq 1 ] || fail "$scenario"
  jq -e '.consecutive_no_mutation_runs == 2' "$state" >/dev/null || fail "$scenario"
  [ "$(line_count '^CREATE supervisor-dead ' "$log")" -eq 1 ] || fail "$scenario"
  [ "$(line_count '^COMMENT supervisor-dead ' "$log")" -eq 0 ] || fail "$scenario"
}

scenario_failure_3() {
  local scenario="failure-3"
  local dir state log out err status
  dir="$(make_tmpdir)" || fail "$scenario"
  state="$dir/state.json"
  log="$dir/assert.log"
  out="$dir/out"
  err="$dir/err"
  create_state "$state" "2026-05-10" 2 || fail "$scenario"
  printf 'CREATE supervisor-dead reason=seed count=2\n' > "$log" || fail "$scenario"

  run_assert "2026-05-10" "$state" "$log" "$out" "$err"
  status=$?

  [ "$status" -eq 1 ] || fail "$scenario"
  jq -e '.consecutive_no_mutation_runs == 3' "$state" >/dev/null || fail "$scenario"
  [ "$(line_count '^CREATE supervisor-dead ' "$log")" -eq 1 ] || fail "$scenario"
  [ "$(line_count '^COMMENT supervisor-dead ' "$log")" -eq 1 ] || fail "$scenario"
}

scenario_edge_missing() {
  local scenario="edge-missing"
  local dir state log out err status
  dir="$(make_tmpdir)" || fail "$scenario"
  state="$dir/missing-state.json"
  log="$dir/assert.log"
  out="$dir/out"
  err="$dir/err"

  run_assert "2026-05-10" "$state" "$log" "$out" "$err"
  status=$?

  [ "$status" -eq 1 ] || fail "$scenario"
  jq -e '.consecutive_no_mutation_runs == 1 and .last_mutation_assertion.reason == "state-file-missing"' "$state" >/dev/null || fail "$scenario"
  [ "$(line_count '^CREATE supervisor-dead ' "$log")" -eq 0 ] || fail "$scenario"
}

scenario_edge_malformed() {
  local scenario="edge-malformed"
  local dir state log out err status
  dir="$(make_tmpdir)" || fail "$scenario"
  state="$dir/state.json"
  log="$dir/assert.log"
  out="$dir/out"
  err="$dir/err"
  printf '{invalid json\n' > "$state" || fail "$scenario"

  run_assert "2026-05-10" "$state" "$log" "$out" "$err"
  status=$?

  [ "$status" -eq 1 ] || fail "$scenario"
  jq -e '.consecutive_no_mutation_runs == 2 and .last_mutation_assertion.reason == "state-file-malformed"' "$state" >/dev/null || fail "$scenario"
  [ "$(line_count '^CREATE supervisor-dead ' "$log")" -eq 1 ] || fail "$scenario"
}

scenario_happy
scenario_failure_1
scenario_failure_2
scenario_failure_3
scenario_edge_missing
scenario_edge_malformed

echo "PASS test-assert-state-mutation: 6 scenarios"
