#!/usr/bin/env bash
set -euo pipefail

fixture=".github/scripts/fixtures/snapshot-fixture.json"
expected=".github/scripts/fixtures/classified-fixture.json"
actual="/tmp/classified-fixture-actual.json"

SUPERVISOR_NOW="2026-05-15T22:00:00Z" bash .github/scripts/classify-clogs.sh "$fixture" > "$actual"

if ! jq -e 'length == 10' "$actual" >/dev/null; then
  echo "FAIL: expected 10 classified items" >&2
  exit 1
fi

if ! diff -u <(jq -S . "$expected") <(jq -S . "$actual"); then
  echo "FAIL: classified fixture mismatch" >&2
  exit 1
fi

if [ "$(jq -r '.[] | select(.number == 303) | .stage' "$actual")" != "review" ]; then
  echo "FAIL: needs-human did not take precedence over copilot-triaging" >&2
  exit 1
fi

empty="/tmp/empty-snapshot.json"
printf '[]\n' > "$empty"
if [ "$(SUPERVISOR_NOW="2026-05-15T22:00:00Z" bash .github/scripts/classify-clogs.sh "$empty" | jq 'length')" -ne 0 ]; then
  echo "FAIL: empty snapshot did not classify to empty array" >&2
  exit 1
fi

bad_taxonomy="/tmp/bad-pipeline-stages.json"
printf '{"stages":["triage"],"classification_rules":{}}\n' > "$bad_taxonomy"
if TAXONOMY_FILE="$bad_taxonomy" bash .github/scripts/classify-clogs.sh "$fixture" >/tmp/bad-classify.out 2>/tmp/bad-classify.err; then
  echo "FAIL: malformed taxonomy unexpectedly passed" >&2
  exit 1
fi
if ! grep -q "bad rule" /tmp/bad-classify.err; then
  echo "FAIL: malformed taxonomy error did not name bad rule" >&2
  exit 1
fi

echo "PASS test-classify: 6 scenarios"
