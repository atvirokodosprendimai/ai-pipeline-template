#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

fixture="$tmp_dir/fixture.json"
output="$tmp_dir/output.txt"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cat > "$fixture" <<'JSON'
[
  {
    "category": "integration-issues",
    "slug": "valid-integration",
    "title": "Valid integration learning",
    "tags": ["github-actions", "queue"],
    "date": "2026-06-05",
    "markdown": "## Problem\n\nIntegration failed.\n\n## Root Cause\n\nQueue drift."
  },
  {
    "category": "logic-errors",
    "slug": "valid-logic",
    "title": "Valid logic learning",
    "tags": ["logic", "synthesis"],
    "date": "2026-06-05",
    "markdown": "## Problem\n\nLogic failed.\n\n## Root Cause\n\nBad assumption."
  },
  {
    "category": "bad-category",
    "slug": "bad-category",
    "title": "Bad category",
    "tags": ["bad"],
    "date": "2026-06-05",
    "markdown": "## Problem\n\nShould be skipped."
  },
  {
    "category": "runtime-errors",
    "slug": "../evil",
    "title": "Traversal",
    "tags": ["bad"],
    "date": "2026-06-05",
    "markdown": "## Problem\n\nShould be skipped."
  }
]
JSON

(
  cd "$tmp_dir"
  bash "$script_dir/compound-render-docs.sh" "$fixture" > "$output"
)

expected_one="$tmp_dir/docs/solutions/integration-issues/valid-integration.md"
expected_two="$tmp_dir/docs/solutions/logic-errors/valid-logic.md"

[[ -f "$expected_one" ]] || fail "missing valid integration doc"
[[ -f "$expected_two" ]] || fail "missing valid logic doc"
[[ "$(find "$tmp_dir/docs/solutions" -type f | wc -l | tr -d ' ')" == "2" ]] || fail "unexpected number of docs written"
[[ ! -e "$tmp_dir/docs/solutions/bad-category/bad-category.md" ]] || fail "bad category was written"
[[ ! -e "$tmp_dir/docs/solutions/runtime-errors/evil.md" ]] || fail "traversal slug was written as sanitized file"
[[ ! -e "$tmp_dir/evil.md" ]] || fail "traversal escaped output directory"

grep -Fq 'title: "Valid integration learning"' "$expected_one" || fail "integration title frontmatter mismatch"
grep -Fq 'category: integration-issues' "$expected_one" || fail "integration category frontmatter mismatch"
grep -Fq 'date: 2026-06-05' "$expected_one" || fail "integration date frontmatter mismatch"
grep -Fq 'tags: [github-actions, queue]' "$expected_one" || fail "integration tags frontmatter mismatch"
grep -Fq '## Problem' "$expected_one" || fail "integration markdown missing"

grep -Fq 'title: "Valid logic learning"' "$expected_two" || fail "logic title frontmatter mismatch"
grep -Fq 'category: logic-errors' "$expected_two" || fail "logic category frontmatter mismatch"
grep -Fq 'tags: [logic, synthesis]' "$expected_two" || fail "logic tags frontmatter mismatch"

grep -Fxq 'docs/solutions/integration-issues/valid-integration.md' "$output" || fail "integration output path missing"
grep -Fxq 'docs/solutions/logic-errors/valid-logic.md' "$output" || fail "logic output path missing"

echo "PASS: compound-render-docs"
