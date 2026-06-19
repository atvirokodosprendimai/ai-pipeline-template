#!/usr/bin/env bash
# Tests for collect-capabilities.sh
# Run: bash company/scripts/test-collect-capabilities.sh
set -euo pipefail

SCRIPT="company/scripts/collect-capabilities.sh"
PASS=0
FAIL=0
TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT

# -- Helpers ------------------------------------------------------

assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected '$expected', got '$actual')"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected to contain '$needle')"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  FAIL: $desc (expected not to contain '$needle')"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  fi
}

assert_status_zero() {
  local desc="$1" status="$2"
  if [ "$status" -eq 0 ]; then
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected exit 0, got $status)"
    FAIL=$((FAIL + 1))
  fi
}

write_prs() {
  local path="$1"
  shift
  printf '%s\n' "$@" > "$path"
}

setup_fixtures() {
  rm -rf "$TMPROOT/solutions"
  mkdir -p "$TMPROOT/solutions/logic-errors"
}

# -- Tests --------------------------------------------------------

echo "=== collect-capabilities.sh tests ==="

echo ""
echo "1. Extracts implementation PR capability with PR number"
setup_fixtures
prs="$TMPROOT/openpanel.json"
write_prs "$prs" '[
  {"number":762,"title":"feat(landing): OpenPanel analytics — track Polar CTA clicks","body":""}
]'
out=$(bash "$SCRIPT" --pr-list-file "$prs" --solutions-dir "$TMPROOT/solutions" 2>/dev/null)
assert_contains "names OpenPanel capability" "OpenPanel analytics" "$out"
assert_contains "cites PR #762" "PR #762" "$out"

echo ""
echo "2. Strips conventional-commit prefix"
assert_eq "exact stripped capability line" "OpenPanel analytics — track Polar CTA clicks (PR #762)" "$out"

echo ""
echo "3. Excludes non-implementation PR types"
setup_fixtures
prs="$TMPROOT/non-impl.json"
write_prs "$prs" '[
  {"number":801,"title":"chore: rotate stale workflow labels","body":""},
  {"number":802,"title":"docs: explain pipeline review checkpoints","body":""},
  {"number":803,"title":"ci: tune observation-loop cron","body":""}
]'
out=$(bash "$SCRIPT" --pr-list-file "$prs" --solutions-dir "$TMPROOT/solutions" 2>/dev/null)
assert_not_contains "chore PR excluded" "rotate stale" "$out"
assert_not_contains "docs PR excluded" "review checkpoints" "$out"
assert_not_contains "ci PR excluded" "observation-loop cron" "$out"
assert_contains "empty implementation set emits sentinel" "(capabilities digest unavailable this run)" "$out"

echo ""
echo "4. Revert PR subtracts matching capability"
setup_fixtures
prs="$TMPROOT/revert.json"
write_prs "$prs" '[
  {"number":763,"title":"Revert \"feat(landing): OpenPanel analytics — track Polar CTA clicks\"","body":""},
  {"number":762,"title":"feat(landing): OpenPanel analytics — track Polar CTA clicks","body":""}
]'
out=$(bash "$SCRIPT" --pr-list-file "$prs" --solutions-dir "$TMPROOT/solutions" 2>/dev/null)
assert_not_contains "reverted capability absent" "OpenPanel analytics" "$out"
assert_contains "reverted-only result emits sentinel" "(capabilities digest unavailable this run)" "$out"

echo ""
echo "5. Budget keeps newest whole lines"
setup_fixtures
prs="$TMPROOT/budget.json"
write_prs "$prs" '[
  {"number":3,"title":"feat: Newest capability","body":""},
  {"number":2,"title":"fix: Middle capability","body":""},
  {"number":1,"title":"refactor: Oldest capability","body":""}
]'
out=$(bash "$SCRIPT" --pr-list-file "$prs" --solutions-dir "$TMPROOT/solutions" --budget 60 2>/dev/null)
assert_contains "newest survives budget" "Newest capability (PR #3)" "$out"
assert_contains "middle survives budget" "Middle capability (PR #2)" "$out"
assert_not_contains "oldest dropped first" "Oldest capability" "$out"
assert_not_contains "no mid-line truncation" "Oldest" "$out"

echo ""
echo "6. Dedups repeated capability titles"
setup_fixtures
prs="$TMPROOT/dedup.json"
write_prs "$prs" '[
  {"number":901,"title":"feat: Duplicate capability","body":""},
  {"number":900,"title":"feat(api): Duplicate capability","body":""}
]'
out=$(bash "$SCRIPT" --pr-list-file "$prs" --solutions-dir "$TMPROOT/solutions" 2>/dev/null)
count=$(echo "$out" | grep -c "Duplicate capability" || true)
assert_eq "duplicate capability appears once" "1" "$count"

echo ""
echo "7. Missing or empty PR fixture degrades gracefully"
setup_fixtures
set +e
out=$(bash "$SCRIPT" --pr-list-file "$TMPROOT/missing.json" --solutions-dir "$TMPROOT/solutions" 2>/dev/null)
status=$?
set -e
assert_status_zero "missing PR fixture exits zero" "$status"
assert_eq "missing PR fixture emits sentinel" "(capabilities digest unavailable this run)" "$out"
empty="$TMPROOT/empty.json"
: > "$empty"
set +e
out=$(bash "$SCRIPT" --pr-list-file "$empty" --solutions-dir "$TMPROOT/solutions" 2>/dev/null)
status=$?
set -e
assert_status_zero "empty PR fixture exits zero" "$status"
assert_eq "empty PR fixture emits sentinel" "(capabilities digest unavailable this run)" "$out"

echo ""
echo "8. Includes docs/solutions titles"
setup_fixtures
prs="$TMPROOT/no-prs.json"
write_prs "$prs" '[]'
cat > "$TMPROOT/solutions/logic-errors/capability.md" <<'EOF'
---
title: Capabilities digest grounds shipped analytics
module: observation-loop
tags: [capabilities]
problem_type: logic-error
---

# Fallback heading should not be used
EOF
out=$(bash "$SCRIPT" --pr-list-file "$prs" --solutions-dir "$TMPROOT/solutions" 2>/dev/null)
assert_contains "solution title appears" "Capabilities digest grounds shipped analytics" "$out"

echo ""
echo "9. State-free run leaves no collector state file"
if find . -name '*capabilities*state*' -print -quit | grep -q .; then
  echo "  FAIL: no capabilities state file should exist"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: no capabilities state file exists"
  PASS=$((PASS + 1))
fi

# Bite check: this harness must fail if capability extraction is broken.
# Temporarily replacing the stripped-title extraction with an empty string
# should make tests 1, 2, 5, 6, and 8 fail; do not commit that mutation.

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
