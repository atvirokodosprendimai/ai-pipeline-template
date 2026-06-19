#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/values-audit.sh"
PASS=0
FAIL=0
TMPDIR=$(mktemp -d)

cleanup() {
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

for cmd in bash git grep; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "FAIL: required tool '$cmd' not found"
    exit 1
  fi
done

assert_eq() {
  local desc="$1"
  local expected="$2"
  local actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected '$expected', got '$actual')"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local desc="$1"
  local needle="$2"
  local file="$3"
  if grep -qF "$needle" "$file"; then
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected '$needle')"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local desc="$1"
  local needle="$2"
  local file="$3"
  if grep -qF "$needle" "$file"; then
    echo "  FAIL: $desc (should not contain '$needle')"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  fi
}

new_repo() {
  local repo="$1"
  mkdir -p "$repo"
  git -C "$repo" init -q
  git -C "$repo" config user.email "values-audit@example.com"
  git -C "$repo" config user.name "Values Audit Test"
  git -C "$repo" config core.hooksPath /dev/null
  printf 'seed\n' > "$repo/README.md"
  git -C "$repo" add README.md
  git -C "$repo" commit -q -m "initial"
}

run_audit() {
  local script="$SCRIPT"
  if [ "$#" -eq 6 ]; then
    script="$1"
    shift
  fi
  local repo="$1"
  local base="$2"
  local head="$3"
  local out="$4"
  local err="$5"
  local status

  set +e
  (cd "$repo" && BASE_SHA="$base" HEAD_SHA="$head" bash "$script") >"$out" 2>"$err"
  status=$?
  set -e
  printf '%s' "$status"
}

combine_logs() {
  local out="$1"
  local err="$2"
  local combined="$3"
  cat "$out" "$err" > "$combined"
}

echo "=== values-audit.sh tests ==="

echo ""
echo "1. #766 component-gating fixture fails"
repo="$TMPDIR/repo-766"
new_repo "$repo"
base=$(git -C "$repo" rev-parse HEAD)
mkdir -p "$repo/api" "$repo/daemon"
cat > "$repo/api/trials.go" <<'GO'
package api

func registerTrialRoute() string {
	return "/v1/accounts/expire-trial"
}
GO
cat > "$repo/daemon/routing.go" <<'GO'
package daemon

func reconcileAccount() string {
	return "pause-on-expiry"
}
GO
git -C "$repo" add api/trials.go daemon/routing.go
git -C "$repo" commit -q -m "add component trial enforcement"
head=$(git -C "$repo" rev-parse HEAD)
out="$TMPDIR/766.out"
err="$TMPDIR/766.err"
status=$(run_audit "$repo" "$base" "$head" "$out" "$err")
combined="$TMPDIR/766.log"
combine_logs "$out" "$err" "$combined"
combined_766="$combined"
assert_eq "#766 fixture exits 1" "1" "$status"
assert_contains "#766 fixture annotates API file" "::error file=api/trials.go" "$combined"
assert_contains "#766 fixture annotates daemon file" "::error file=daemon/routing.go" "$combined"

echo ""
echo "2. Clean managed-layer billing diff passes"
repo="$TMPDIR/repo-managed"
new_repo "$repo"
base=$(git -C "$repo" rev-parse HEAD)
mkdir -p "$repo/cloudroof"
cat > "$repo/cloudroof/billing.md" <<'MD'
# cloudroof billing

Hosted ingress signup creates invoices for managed service usage.
When a hosted subscription ends, the hosted control-plane service can stop serving the account.
Self-hosted components keep their full local functionality.
MD
git -C "$repo" add cloudroof/billing.md
git -C "$repo" commit -q -m "document managed billing"
head=$(git -C "$repo" rev-parse HEAD)
out="$TMPDIR/managed.out"
err="$TMPDIR/managed.err"
status=$(run_audit "$repo" "$base" "$head" "$out" "$err")
assert_eq "managed-layer billing exits 0" "0" "$status"

echo ""
echo "3. Unrelated diff passes cheaply"
repo="$TMPDIR/repo-unrelated"
new_repo "$repo"
base=$(git -C "$repo" rev-parse HEAD)
mkdir -p "$repo/docs"
printf '# Docs\n\nOperational note.\n' > "$repo/docs/note.md"
git -C "$repo" add docs/note.md
git -C "$repo" commit -q -m "add note"
head=$(git -C "$repo" rev-parse HEAD)
out="$TMPDIR/unrelated.out"
err="$TMPDIR/unrelated.err"
status=$(run_audit "$repo" "$base" "$head" "$out" "$err")
combined="$TMPDIR/unrelated.log"
combine_logs "$out" "$err" "$combined"
assert_eq "unrelated diff exits 0" "0" "$status"
assert_contains "unrelated diff reports no relevant paths" "No values-audit relevant paths touched" "$combined"

echo ""
echo "4. Removing a deny-list pattern makes the #766 fixture pass"
repo="$TMPDIR/repo-neutralized"
new_repo "$repo"
base=$(git -C "$repo" rev-parse HEAD)
mkdir -p "$repo/api" "$repo/daemon"
cat > "$repo/api/trials.go" <<'GO'
package api

func registerTrialRoute() string {
	return "/v1/accounts/expire-trial"
}
GO
cat > "$repo/daemon/routing.go" <<'GO'
package daemon

func reconcileAccount() string {
	return "pause-on-expiry"
}
GO
git -C "$repo" add api/trials.go daemon/routing.go
git -C "$repo" commit -q -m "add component trial enforcement"
head=$(git -C "$repo" rev-parse HEAD)
out="$TMPDIR/neutralized.out"
err="$TMPDIR/neutralized.err"
muted="$TMPDIR/values-audit-muted.sh"
grep -F -v \
  -e 'trial[_ -]?expired' \
  -e 'pause[-_ ]?on[-_ ]?expiry' \
  "$SCRIPT" > "$muted"
chmod +x "$muted"
assert_contains "production script includes expire-trial pattern" "expire[_ -]?trial" "$SCRIPT"
assert_contains "production script includes pause-on-expiry pattern" "pause[-_ ]?on[-_ ]?expiry" "$SCRIPT"
status=$(run_audit "$repo" "$base" "$head" "$out" "$err")
assert_eq "original script still fails #766 fixture" "1" "$status"
status=$(run_audit "$muted" "$repo" "$base" "$head" "$out" "$err")
assert_eq "removing #766 deny-list pattern makes fixture pass" "0" "$status"

echo ""
echo "5. Matched values are not echoed"
assert_not_contains "does not echo expire-trial" "expire-trial" "$combined_766"
assert_not_contains "does not echo pause-on-expiry" "pause-on-expiry" "$combined_766"
assert_not_contains "does not echo source line" "registerTrialRoute" "$combined_766"

echo ""
echo "6. Changed spec files are scanned"
repo="$TMPDIR/repo-spec"
new_repo "$repo"
base=$(git -C "$repo" rev-parse HEAD)
mkdir -p "$repo/specs"
cat > "$repo/specs/payments.md" <<'MD'
# Spec

The daemon should use account_state gating before it starts routing.
MD
git -C "$repo" add specs/payments.md
git -C "$repo" commit -q -m "add spec"
head=$(git -C "$repo" rev-parse HEAD)
out="$TMPDIR/spec.out"
err="$TMPDIR/spec.err"
status=$(run_audit "$repo" "$base" "$head" "$out" "$err")
combined_spec="$TMPDIR/spec.log"
combine_logs "$out" "$err" "$combined_spec"
assert_eq "spec fixture exits 1" "1" "$status"
assert_contains "spec fixture annotates spec file" "::error file=specs/payments.md" "$combined_spec"

echo ""
echo "=== values-audit.sh result: PASS=$PASS FAIL=$FAIL ==="
if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
