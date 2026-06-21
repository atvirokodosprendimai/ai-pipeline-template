#!/usr/bin/env bash
# Tests for conflict-heal/rebase.sh
# Run: bash company/scripts/conflict-heal/test-rebase.sh
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
#   REBASE_EXIT (default 0): exit code of `git rebase origin/main`
#   DIFF_EXIT   (default 1): exit code of `git diff --quiet origin/main`
#                            (git: 0 == no delta/empty, 1 == has delta)
mkdir -p "$TMPDIR/bin"
cat > "$TMPDIR/bin/git" <<'GIT'
#!/usr/bin/env bash
echo "$@" >> "$GIT_LOG"
# Strip a leading "-C <dir>" so the real subcommand is $1.
if [[ "${1:-}" == "-C" ]]; then shift 2; fi
case "${1:-}" in
  clone) exit 0 ;;
  fetch) exit 0 ;;
  checkout) exit 0 ;;
  rebase)
    if [[ "${2:-}" == "--abort" ]]; then exit 0; fi
    exit "${REBASE_EXIT:-0}" ;;
  diff) exit "${DIFF_EXIT:-1}" ;;
  push) exit 0 ;;
  *) exit 0 ;;
esac
GIT
chmod +x "$TMPDIR/bin/git"
export GIT_LOG

run_rebase() {
  # Run rebase.sh with the mock git on PATH; capture its OUTCOME line.
  : > "$GIT_LOG"
  PATH="$TMPDIR/bin:$ORIG_PATH" \
    REBASE_EXIT="${REBASE_EXIT:-0}" DIFF_EXIT="${DIFF_EXIT:-1}" \
    bash "$REAL_SCRIPT_DIR/rebase.sh" "$@"
}

echo "── conflict-heal/rebase.sh ──"

# 1. bot branch, clean rebase, real delta → rebased + force-with-lease push
out=$(REBASE_EXIT=0 DIFF_EXIT=1 run_rebase wgmesh 7 bot/impl-7)
assert_contains "clean rebase with delta → rebased" "OUTCOME=rebased" "$out"
git_log=$(cat "$GIT_LOG")
assert_contains "push uses --force-with-lease" "push --force-with-lease origin bot/impl-7" "$git_log"
assert_not_contains "never bare --force" "push --force origin" "$git_log"

# 2. bot branch, rebase conflict → abort, conflict, NO push
out=$(REBASE_EXIT=1 DIFF_EXIT=1 run_rebase wgmesh 744 bot/impl-744)
assert_contains "rebase conflict → conflict" "OUTCOME=conflict" "$out"
git_log=$(cat "$GIT_LOG")
assert_contains "conflict aborts the rebase" "rebase --abort" "$git_log"
assert_not_contains "conflict path never pushes" "push" "$git_log"

# 3. bot branch, clean rebase but empty diff vs main → empty, NO push (R6)
out=$(REBASE_EXIT=0 DIFF_EXIT=0 run_rebase wgmesh 755 bot/impl-755)
assert_contains "empty diff → empty" "OUTCOME=empty" "$out"
git_log=$(cat "$GIT_LOG")
assert_not_contains "empty path never pushes" "push" "$git_log"

# 4. non-bot branch → skipped, NO git invoked at all (R4 — load-bearing guard)
out=$(run_rebase wgmesh 9 feature/human-9)
assert_contains "non-bot branch → skipped" "OUTCOME=skipped REASON=non-bot-branch" "$out"
git_log=$(cat "$GIT_LOG")
assert_eq "non-bot branch reaches ZERO git calls" "" "$git_log"

# 5. missing args → skipped
out=$(run_rebase wgmesh)
assert_contains "missing args → skipped" "OUTCOME=skipped REASON=missing-args" "$out"

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
