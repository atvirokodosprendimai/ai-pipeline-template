#!/usr/bin/env bash
set -euo pipefail

classified=".github/scripts/fixtures/classified-fixture.json"
expected=".github/scripts/fixtures/ranked-fixture.json"
ranked="/tmp/ranked-fixture-actual.json"
recommended="/tmp/ranked-fixture-recommended.json"

SUPERVISOR_NOW="2026-05-15T22:00:00Z" bash .github/scripts/rank-clogs.sh "$classified" > "$ranked"
bash .github/scripts/recommend-actions.sh "$ranked" > "$recommended"

if ! diff -u <(jq -S . "$expected") <(jq -S . "$recommended"); then
  echo "FAIL: ranked fixture mismatch" >&2
  exit 1
fi

empty="/tmp/empty-classified.json"
printf '[]\n' > "$empty"
empty_ranked="/tmp/empty-ranked.json"
SUPERVISOR_NOW="2026-05-15T22:00:00Z" bash .github/scripts/rank-clogs.sh "$empty" > "$empty_ranked"
if ! jq -e '.top == [] and .stage_summary.unknown == 0' "$empty_ranked" >/dev/null; then
  echo "FAIL: empty classified snapshot did not produce empty ranked output" >&2
  exit 1
fi

tie="/tmp/tie-classified.json"
jq -n '
  [
    {repo:"r",type:"issue",number:2,title:"newer",labels:[],created_at:"2026-05-15T10:00:00Z",stage:"build",dwell_hours:10},
    {repo:"r",type:"issue",number:1,title:"older",labels:[],created_at:"2026-05-15T09:00:00Z",stage:"build",dwell_hours:10}
  ]
' > "$tie"
if [ "$(SUPERVISOR_NOW="2026-05-15T22:00:00Z" bash .github/scripts/rank-clogs.sh "$tie" | jq -r '.top[0].number')" != "1" ]; then
  echo "FAIL: tie did not break by older created_at first" >&2
  exit 1
fi

unknown_stage="/tmp/unknown-stage-ranked.json"
jq -n '{generated_at:"2026-05-15T22:00:00Z",top:[{rank:1,stage:"new-stage",number:9,repo:"r",title:"x"}],stage_summary:{},unknown:[]}' > "$unknown_stage"
bash .github/scripts/recommend-actions.sh "$unknown_stage" >/tmp/unknown-stage.out 2>/tmp/unknown-stage.err
if ! jq -e '.top[0].recommended_action == null' /tmp/unknown-stage.out >/dev/null; then
  echo "FAIL: missing recommendation did not fall back to null" >&2
  exit 1
fi
if ! grep -q "warning: no recommended action" /tmp/unknown-stage.err; then
  echo "FAIL: missing recommendation did not warn" >&2
  exit 1
fi

# Stdin-pipe equivalence for rank-clogs.sh and recommend-actions.sh.
# Regression guard for double-stdin-read.
rank_stdin_out="/tmp/ranked-stdin.out"
SUPERVISOR_NOW="2026-05-15T22:00:00Z" bash .github/scripts/rank-clogs.sh < "$classified" > "$rank_stdin_out"
if ! diff -u <(jq -S . "$ranked") <(jq -S . "$rank_stdin_out"); then
  echo "FAIL: stdin rank diverged from file rank" >&2
  exit 1
fi
recommend_stdin_out="/tmp/recommended-stdin.out"
bash .github/scripts/recommend-actions.sh < "$ranked" > "$recommend_stdin_out"
if ! diff -u <(jq -S . "$recommended") <(jq -S . "$recommend_stdin_out"); then
  echo "FAIL: stdin recommend diverged from file recommend" >&2
  exit 1
fi

echo "PASS test-rank: 8 scenarios"
