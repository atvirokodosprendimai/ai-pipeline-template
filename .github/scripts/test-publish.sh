#!/usr/bin/env bash
set -euo pipefail

ranked=".github/scripts/fixtures/ranked-fixture.json"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

state="$tmpdir/state.json"
log="$tmpdir/publish.log"

SUPERVISOR_PUBLISH_DRY_RUN=1 \
SUPERVISOR_PUBLISH_LOG="$log" \
GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
bash .github/scripts/publish-rank.sh "$ranked" "$state" >/tmp/publish-first.out

if ! jq -e '.run_number == 1 and .rank_changed == false and (.last_run_top_ids | length) == 3' "$state" >/dev/null; then
  echo "FAIL: first dry-run state was not written correctly" >&2
  exit 1
fi

SUPERVISOR_PUBLISH_DRY_RUN=1 \
SUPERVISOR_PUBLISH_LOG="$log" \
GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
bash .github/scripts/publish-rank.sh "$ranked" "$state" >/tmp/publish-second.out

if ! jq -e '.run_number == 2 and .rank_changed == false' "$state" >/dev/null; then
  echo "FAIL: second dry-run should not mark rank changed" >&2
  exit 1
fi

changed="$tmpdir/changed.json"
jq '.top = ([.top[1], .top[0]] + .top[2:]) | .top |= to_entries | .top = (.top | map(.value + {rank:(.key + 1)}))' "$ranked" > "$changed"

SUPERVISOR_PUBLISH_DRY_RUN=1 \
SUPERVISOR_PUBLISH_LOG="$log" \
GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
bash .github/scripts/publish-rank.sh "$changed" "$state" >/tmp/publish-third.out

if ! jq -e '.run_number == 3 and .rank_changed == true' "$state" >/dev/null; then
  echo "FAIL: changed top-3 should mark rank_changed" >&2
  exit 1
fi

if GH_TOKEN="" GH_REPO="atvirokodosprendimai/ai-pipeline-template" bash .github/scripts/publish-rank.sh "$ranked" "$tmpdir/no-token.json" >/tmp/publish-no-token.out 2>/tmp/publish-no-token.err; then
  echo "FAIL: missing GH_TOKEN unexpectedly passed" >&2
  exit 1
fi
if ! grep -q "GH_TOKEN is required" /tmp/publish-no-token.err; then
  echo "FAIL: missing GH_TOKEN error was not explicit" >&2
  exit 1
fi

echo "PASS test-publish: 4 scenarios"
