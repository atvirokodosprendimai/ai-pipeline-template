#!/usr/bin/env bash
set -euo pipefail

ranked=".github/scripts/fixtures/ranked-fixture.json"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

state="$tmpdir/state.json"
log="$tmpdir/publish.log"
sentinel="$tmpdir/material.sentinel"

# Scenario 1: first dry-run → material changes (no prior fingerprint) → state written.
SUPERVISOR_PUBLISH_DRY_RUN=1 \
SUPERVISOR_PUBLISH_LOG="$log" \
SUPERVISOR_MATERIAL_SENTINEL="$sentinel" \
GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
bash .github/scripts/publish-rank.sh "$ranked" "$state" >/tmp/publish-first.out

if ! jq -e '.run_number == 1 and .rank_changed == false and (.last_run_top_ids | length) == 3 and (.material_fingerprint | type == "string") and (.material_fingerprint | length == 64)' "$state" >/dev/null; then
  echo "FAIL: first dry-run state missing run_number/material_fingerprint" >&2
  exit 1
fi
if [ "$(cat "$sentinel")" != "true" ]; then
  echo "FAIL: first run sentinel should be 'true' (no prior fingerprint)" >&2
  exit 1
fi
first_fp="$(jq -r '.material_fingerprint' "$state")"

# Scenario 2: second dry-run same input → material UNCHANGED → state NOT rewritten.
SUPERVISOR_PUBLISH_DRY_RUN=1 \
SUPERVISOR_PUBLISH_LOG="$log" \
SUPERVISOR_MATERIAL_SENTINEL="$sentinel" \
GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
bash .github/scripts/publish-rank.sh "$ranked" "$state" >/tmp/publish-second.out

if [ "$(cat "$sentinel")" != "false" ]; then
  echo "FAIL: second run sentinel should be 'false' (no material change)" >&2
  exit 1
fi
if ! jq -e --arg fp "$first_fp" '.run_number == 1 and .material_fingerprint == $fp' "$state" >/dev/null; then
  echo "FAIL: second run with same input must not advance run_number or fingerprint" >&2
  exit 1
fi

# Scenario 3: third dry-run with reordered top → material CHANGED → state advances.
changed="$tmpdir/changed.json"
jq '.top = ([.top[1], .top[0]] + .top[2:]) | .top |= to_entries | .top = (.top | map(.value + {rank:(.key + 1)}))' "$ranked" > "$changed"

SUPERVISOR_PUBLISH_DRY_RUN=1 \
SUPERVISOR_PUBLISH_LOG="$log" \
SUPERVISOR_MATERIAL_SENTINEL="$sentinel" \
GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
bash .github/scripts/publish-rank.sh "$changed" "$state" >/tmp/publish-third.out

if [ "$(cat "$sentinel")" != "true" ]; then
  echo "FAIL: third run sentinel should be 'true' (material changed)" >&2
  exit 1
fi
if ! jq -e --arg fp "$first_fp" '.run_number == 2 and .rank_changed == true and .material_fingerprint != $fp' "$state" >/dev/null; then
  echo "FAIL: changed top-3 must advance run_number, set rank_changed, and shift fingerprint" >&2
  exit 1
fi

# Scenario 4: missing GH_TOKEN → error (production path only).
if GH_TOKEN="" GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
   SUPERVISOR_MATERIAL_SENTINEL="$tmpdir/no-token.sentinel" \
   bash .github/scripts/publish-rank.sh "$ranked" "$tmpdir/no-token.json" >/tmp/publish-no-token.out 2>/tmp/publish-no-token.err; then
  echo "FAIL: missing GH_TOKEN unexpectedly passed" >&2
  exit 1
fi
if ! grep -q "GH_TOKEN is required" /tmp/publish-no-token.err; then
  echo "FAIL: missing GH_TOKEN error was not explicit" >&2
  exit 1
fi

# Scenario 5: same fingerprint, only stage_summary differs → material CHANGED.
stage_diff="$tmpdir/stage-diff.json"
jq '.stage_summary.spec = ((.stage_summary.spec // 0) + 1)' "$ranked" > "$stage_diff"
SUPERVISOR_PUBLISH_DRY_RUN=1 \
SUPERVISOR_PUBLISH_LOG="$log" \
SUPERVISOR_MATERIAL_SENTINEL="$sentinel" \
GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
bash .github/scripts/publish-rank.sh "$stage_diff" "$state" >/tmp/publish-fifth.out

if [ "$(cat "$sentinel")" != "true" ]; then
  echo "FAIL: stage_summary change should flip sentinel to 'true'" >&2
  exit 1
fi

# Scenario 6: same top + same stage_summary + only recommended_action shift → material CHANGED.
prev_fp="$(jq -r '.material_fingerprint' "$state")"
action_diff="$tmpdir/action-diff.json"
jq '.top[0].recommended_action = "post-rah-bounty"' "$stage_diff" > "$action_diff"
SUPERVISOR_PUBLISH_DRY_RUN=1 \
SUPERVISOR_PUBLISH_LOG="$log" \
SUPERVISOR_MATERIAL_SENTINEL="$sentinel" \
GH_REPO="atvirokodosprendimai/ai-pipeline-template" \
bash .github/scripts/publish-rank.sh "$action_diff" "$state" >/tmp/publish-sixth.out

if [ "$(cat "$sentinel")" != "true" ]; then
  echo "FAIL: recommended_action change should flip sentinel to 'true'" >&2
  exit 1
fi
if ! jq -e --arg fp "$prev_fp" '.material_fingerprint != $fp' "$state" >/dev/null; then
  echo "FAIL: recommended_action change should produce a new fingerprint" >&2
  exit 1
fi

echo "PASS test-publish: 6 scenarios"
