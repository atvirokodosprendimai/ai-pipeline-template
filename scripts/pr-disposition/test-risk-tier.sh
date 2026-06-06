#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

CONFIG="$TMPDIR/config.local.yaml"
cat > "$CONFIG" <<'YAML'
pr_disposition_high_risk_paths:
  - '^private-risk/'
YAML

export PR_DISPOSITION_CONFIG="$CONFIG"

pass=0
total=0

assert_tier() {
  local name="$1" expected="$2" input="$3"
  total=$((total + 1))
  local actual
  actual=$(printf '%s' "$input" | bash "$ROOT_DIR/scripts/pr-disposition/risk-tier.sh")
  if [[ "$actual" == "$expected" ]]; then
    pass=$((pass + 1))
  else
    echo "FAIL ${name}: expected ${expected}, got ${actual}" >&2
    exit 1
  fi
}

assert_tier "plain docs are low" "low" $'docs/README.md\nscripts/check.sh\n'
assert_tier "outreach docs are high" "high" $'docs/outreach/prospect.md\n'
assert_tier "customer docs are high" "high" $'docs/customers/acme.md\n'
assert_tier "system prompt is high" "high" $'company/system-prompt.md\n'
assert_tier "auth path is high" "high" $'src/auth/login.ts\n'
assert_tier "secret filename is high" "high" $'ops/secret-rotation.md\n'
assert_tier "payment path is high" "high" $'services/payments/stripe.ts\n'
assert_tier "config override is high" "high" $'private-risk/notes.md\n'
assert_tier "empty list is low" "low" ''

echo "PASS ${pass}/${total}"
