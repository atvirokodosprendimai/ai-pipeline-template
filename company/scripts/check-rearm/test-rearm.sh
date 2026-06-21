#!/usr/bin/env bash
# Tests for check-rearm/rearm.sh
# Run: bash company/scripts/check-rearm/test-rearm.sh
set -euo pipefail

PASS=0
FAIL=0
TMPDIR=$(mktemp -d)
ORIG_PATH="$PATH"

cleanup() {
  PATH="$ORIG_PATH"
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

REAL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_LOG="$TMPDIR/git.log"

# ── Helpers ───────────────────────────────────────────────────────

assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS: $desc"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected '$expected', got '$actual')"; FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  PASS: $desc"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected to contain '$needle')"; FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  FAIL: $desc (should NOT contain '$needle')"; FAIL=$((FAIL + 1))
  else
    echo "  PASS: $desc"; PASS=$((PASS + 1))
  fi
}

# ── Mock git ──────────────────────────────────────────────────────
# Logs every invocation to GIT_LOG and simulates outcomes via env:
#   PUSH_EXIT (default 0): exit code of `git push origin <branch>`
mkdir -p "$TMPDIR/bin"
cat > "$TMPDIR/bin/git" <<'GIT'
#!/usr/bin/env bash
echo "$@" >> "$GIT_LOG"
# Strip a leading "-C <dir>" so the real subcommand is $1.
if [[ "${1:-}" == "-C" ]]; then shift 2; fi
case "${1:-}" in
  clone) exit 0 ;;
  checkout) exit 0 ;;
  config) exit 0 ;;
  commit) exit 0 ;;
  push) exit "${PUSH_EXIT:-0}" ;;
  *) exit 0 ;;
esac
GIT
chmod +x "$TMPDIR/bin/git"
export GIT_LOG

run_rearm() {
  : > "$GIT_LOG"
  PATH="$TMPDIR/bin:$ORIG_PATH" \
    PUSH_EXIT="${PUSH_EXIT:-0}" \
    bash "$REAL_SCRIPT_DIR/rearm.sh" "$@"
}

echo "── check-rearm/rearm.sh ──"

# 1. bot branch, push ok → rearmed; empty commit + normal push, NO force
out=$(PUSH_EXIT=0 run_rearm wgmesh 782 bot/impl-782)
assert_contains "bot branch push ok → rearmed" "OUTCOME=rearmed" "$out"
git_log=$(cat "$GIT_LOG")
assert_contains "creates an empty commit" "commit --allow-empty" "$git_log"
assert_contains "pushes the branch" "push origin bot/impl-782" "$git_log"
assert_not_contains "never force-pushes" "--force" "$git_log"

# 2. bot branch, push fails (non-fast-forward) → error, no crash
out=$(PUSH_EXIT=1 run_rearm wgmesh 782 bot/impl-782)
assert_contains "push failure → error" "OUTCOME=error REASON=push-failed" "$out"

# 3. non-bot branch → skipped, NO git invoked at all (R3 — load-bearing guard)
out=$(run_rearm wgmesh 9 feature/human-9)
assert_contains "non-bot branch → skipped" "OUTCOME=skipped REASON=non-bot-branch" "$out"
git_log=$(cat "$GIT_LOG")
assert_eq "non-bot branch reaches ZERO git calls" "" "$git_log"

# 4. missing args → skipped
out=$(run_rearm wgmesh)
assert_contains "missing args → skipped" "OUTCOME=skipped REASON=missing-args" "$out"

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
