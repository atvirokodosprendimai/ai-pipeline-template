#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

mkdir -p "$TMPDIR/bin" "$TMPDIR/company/scripts"
export PATH="$TMPDIR/bin:$PATH"
export PR_DISPOSITION_STATE="$TMPDIR/state.json"
printf '{"ledger":[],"acted_fingerprints":[]}\n' > "$PR_DISPOSITION_STATE"

cat > "$TMPDIR/bin/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$GH_LOG"
SH
chmod +x "$TMPDIR/bin/gh"

pass=0
total=0

assert_contains() {
  local name="$1" needle="$2" file="$3"
  total=$((total + 1))
  if grep -qF -- "$needle" "$file"; then
    pass=$((pass + 1))
  else
    echo "FAIL ${name}: missing ${needle}" >&2
    exit 1
  fi
}

assert_not_contains() {
  local name="$1" needle="$2" file="$3"
  total=$((total + 1))
  if ! grep -qF -- "$needle" "$file" 2>/dev/null; then
    pass=$((pass + 1))
  else
    echo "FAIL ${name}: unexpected ${needle}" >&2
    exit 1
  fi
}

assert_jq() {
  local name="$1" expr="$2" file="$3"
  total=$((total + 1))
  if jq -e "$expr" "$file" >/dev/null; then
    pass=$((pass + 1))
  else
    echo "FAIL ${name}: jq ${expr}" >&2
    cat "$file" >&2
    exit 1
  fi
}

GH_LOG="$TMPDIR/gh-reject.log"
export GH_LOG
SANITISE_SH="$TMPDIR/reject-sanitise.sh"
cat > "$SANITISE_SH" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
exit 1
SH
chmod +x "$SANITISE_SH"
export PR_DISPOSITION_SANITISE="$SANITISE_SH"
reject_json='{"class":"stale","risk_tier":"low","reasons":["contains rejected material"]}'
if bash "$ROOT_DIR/scripts/pr-disposition/close-stale.sh" 11 "$reject_json" >/dev/null; then
  :
else
  echo "FAIL sanitise reject should escalate without failing" >&2
  exit 1
fi
assert_not_contains "reject does not close" "pr close" "$GH_LOG"
assert_contains "reject adds needs-human" "pr edit 11 --add-label needs-human" "$GH_LOG"
assert_contains "reject comments" "pr comment 11 --body" "$GH_LOG"
assert_jq "reject leaves ledger empty" '.ledger | length == 0' "$PR_DISPOSITION_STATE"

GH_LOG="$TMPDIR/gh-close.log"
export GH_LOG
unset PR_DISPOSITION_SANITISE
normal_json='{"class":"stale","risk_tier":"low","reasons":["A newer PR supersedes this implementation.","CI is red."]}'
bash "$ROOT_DIR/scripts/pr-disposition/close-stale.sh" 12 "$normal_json"
assert_contains "normal closes PR" "pr close 12 --comment" "$GH_LOG"
assert_contains "normal deletes branch" "--delete-branch" "$GH_LOG"
assert_jq "normal appends ledger" '.ledger | length == 1' "$PR_DISPOSITION_STATE"
assert_jq "ledger keeps reasons" '.ledger[0].reasons | index("A newer PR supersedes this implementation.") != null' "$PR_DISPOSITION_STATE"

echo "PASS ${pass}/${total}"
