#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

queue_file="$tmp_dir/compound-queue.jsonl"
long_body="$(printf 'x%.0s' {1..900})"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

export PR_NUMBER="123"
export PR_TITLE="Implement Issue #45 compound queue"
export PR_BODY="$long_body"
export ISSUE_NUMBER=""
export FILES=$'.github/workflows/example.yml\nsrc/example.sh'
export MERGED_AT="2026-06-05T12:34:56Z"

bash "$script_dir/compound-queue-append.sh" "$queue_file"

jq -e . "$queue_file" >/dev/null || fail "appended line is not valid JSON"

[[ "$(jq -r '.pr' "$queue_file")" == "123" ]] || fail "pr mismatch"
[[ "$(jq -r '.title' "$queue_file")" == "$PR_TITLE" ]] || fail "title mismatch"
[[ "$(jq -r '.issue == null' "$queue_file")" == "true" ]] || fail "empty ISSUE_NUMBER did not produce null"
[[ "$(jq -r '.files | length' "$queue_file")" == "2" ]] || fail "files length mismatch"
[[ "$(jq -r '.files[0]' "$queue_file")" == ".github/workflows/example.yml" ]] || fail "first file mismatch"
[[ "$(jq -r '.merged_at' "$queue_file")" == "$MERGED_AT" ]] || fail "merged_at mismatch"
[[ "$(jq -r '.body_excerpt | length' "$queue_file")" == "800" ]] || fail "body_excerpt not truncated to 800 chars"

export PR_NUMBER="124"
export PR_TITLE="Second PR"
export PR_BODY="short body"
export ISSUE_NUMBER="77"
export FILES="README.md"
export MERGED_AT="2026-06-05T13:00:00Z"

bash "$script_dir/compound-queue-append.sh" "$queue_file"

[[ "$(wc -l < "$queue_file" | tr -d ' ')" == "2" ]] || fail "second call did not append a second line"
[[ "$(tail -n 1 "$queue_file" | jq -r '.issue')" == "77" ]] || fail "non-empty ISSUE_NUMBER mismatch"

echo "PASS: compound-queue-append"
