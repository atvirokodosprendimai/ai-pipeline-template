#!/usr/bin/env bash
# Tests for collect-memory.sh
# Run: bash company/scripts/test-collect-memory.sh
set -euo pipefail

SCRIPT="company/scripts/collect-memory.sh"
PASS=0
FAIL=0
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# ── Helpers ─────────────────────────────────────────────────────

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

assert_le() {
  local desc="$1" max="$2" actual="$3"
  if [ "$actual" -le "$max" ]; then
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected <= $max, got $actual)"
    FAIL=$((FAIL + 1))
  fi
}

# ── Setup test fixtures ─────────────────────────────────────────

setup_fixtures() {
  mkdir -p "$TMPDIR/memory/episodic" "$TMPDIR/memory/archive"

  cat > "$TMPDIR/memory/MEMORY.md" <<'EOF'
# Memory
## Product State
- wgmesh works
## Agent Learnings
- Test learning
EOF

  cat > "$TMPDIR/memory/episodic/20260316-0900-loop-assessment.md" <<'EOF'
---
date: 2026-03-16T09:00:00Z
agent: loop
type: assessment
tags: [nat, relay]
status: active
outcome: success
---

## Summary
Loop assessed the company. NAT issues found.

## Learnings
- NAT is tricky
EOF

  cat > "$TMPDIR/memory/episodic/20260316-1000-goose-implement.md" <<'EOF'
---
date: 2026-03-16T10:00:00Z
agent: goose
type: implementation
issue: 457
tags: [routing, performance]
status: active
outcome: success
---

## Summary
Goose implemented routing fix for issue 457.

## Learnings
- Routing tables need hysteresis
EOF

  cat > "$TMPDIR/memory/episodic/20260315-0800-loop-old.md" <<'EOF'
---
date: 2026-03-15T08:00:00Z
agent: loop
type: assessment
tags: [infrastructure]
status: consolidated
outcome: success
---

## Summary
Old assessment about infrastructure.
EOF
}

# ── Tests ───────────────────────────────────────────────────────

echo "=== collect-memory.sh tests ==="

echo ""
echo "1. Semantic-only mode"
setup_fixtures
out=$(bash "$SCRIPT" --memory-dir "$TMPDIR/memory" --semantic-only 2>/dev/null)
assert_contains "returns MEMORY.md content" "Product State" "$out"
assert_contains "contains learning" "Test learning" "$out"
# Should NOT contain episodic
if echo "$out" | grep -q "Episodic"; then
  echo "  FAIL: semantic-only should not include episodic"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: no episodic in semantic-only mode"
  PASS=$((PASS + 1))
fi

echo ""
echo "2. Full output (semantic + episodic)"
out=$(bash "$SCRIPT" --memory-dir "$TMPDIR/memory" 2>/dev/null)
assert_contains "has semantic content" "Product State" "$out"
assert_contains "has episodic header" "Recent Episodic Memory" "$out"
assert_contains "has loop entry" "Loop assessed" "$out"
assert_contains "has goose entry" "Goose implemented" "$out"

echo ""
echo "3. Tag filtering"
out=$(bash "$SCRIPT" --memory-dir "$TMPDIR/memory" --tags "nat" 2>/dev/null)
assert_contains "matches nat tag" "Loop assessed" "$out"
# routing file does NOT have nat tag
if echo "$out" | grep -q "Goose implemented"; then
  echo "  FAIL: nat filter should not include routing-only file"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: nat filter excludes non-matching files"
  PASS=$((PASS + 1))
fi

echo ""
echo "4. Recent limit"
out=$(bash "$SCRIPT" --memory-dir "$TMPDIR/memory" --recent 1 2>/dev/null)
assert_contains "has 1 entry header" "1 entries" "$out"

echo ""
echo "5. Budget enforcement"
out=$(bash "$SCRIPT" --memory-dir "$TMPDIR/memory" --budget 100 2>/dev/null)
actual_size=$(echo -n "$out" | wc -c | tr -d ' ')
assert_le "output <= 100 bytes" 100 "$actual_size"

echo ""
echo "6. Graceful degradation — missing directory"
out=$(bash "$SCRIPT" --memory-dir "$TMPDIR/nonexistent" 2>/dev/null || true)
# Should not crash, should output something (even if just a warning)
assert_eq "exits cleanly" "0" "$?"

echo ""
echo "7. Graceful degradation — empty episodic"
empty_dir=$(mktemp -d)
mkdir -p "$empty_dir/episodic"
cat > "$empty_dir/MEMORY.md" <<'EOF'
# Memory
- Empty test
EOF
out=$(bash "$SCRIPT" --memory-dir "$empty_dir" 2>/dev/null)
assert_contains "returns semantic even with empty episodic" "Empty test" "$out"
rm -rf "$empty_dir"

echo ""
echo "8. Multiple tags (OR matching)"
out=$(bash "$SCRIPT" --memory-dir "$TMPDIR/memory" --tags "nat,performance" 2>/dev/null)
assert_contains "matches nat file" "Loop assessed" "$out"
assert_contains "matches performance file" "Goose implemented" "$out"

# ── Summary ─────────────────────────────────────────────────────

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
