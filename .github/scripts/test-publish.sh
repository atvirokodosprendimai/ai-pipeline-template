#!/usr/bin/env bash
set -euo pipefail

ranked=".github/scripts/fixtures/ranked-fixture.json"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

state="$tmpdir/state.json"
log="$tmpdir/publish.log"
sentinel="$tmpdir/material.sentinel"

repo="atvirokodosprendimai/ai-pipeline-template"

make_gh_shim() {
  local shim_dir="$1"
  mkdir -p "$shim_dir"
  cat > "$shim_dir/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

{
  first=1
  for arg in "$@"; do
    if [ "$first" -eq 1 ]; then
      first=0
    else
      printf ' '
    fi
    printf '%q' "$arg"
  done
  printf '\n'
} >> "$GH_RECORD"

case "$1 $2" in
  "issue list")
    cat "$GH_ISSUES_JSON"
    ;;
  "issue create")
    echo "https://github.com/${GH_REPO}/issues/777"
    ;;
  "issue edit"|"issue close"|"issue comment")
    ;;
  *)
    echo "unexpected gh invocation: $*" >&2
    exit 1
    ;;
esac
SH
  chmod +x "$shim_dir/gh"
}

run_production_dedup_case() {
  local case_name="$1"
  local issues_payload="$2"
  local state_file="$tmpdir/${case_name}-state.json"
  local record_file="$tmpdir/${case_name}-gh.log"
  local issues_file="$tmpdir/${case_name}-issues.json"
  local shim_dir="$tmpdir/${case_name}-bin"
  local sentinel_file="$tmpdir/${case_name}-sentinel"

  printf '%s\n' "$issues_payload" > "$issues_file"
  : > "$record_file"
  make_gh_shim "$shim_dir"

  GH_TOKEN="test-token" \
  GH_REPO="$repo" \
  GH_RECORD="$record_file" \
  GH_ISSUES_JSON="$issues_file" \
  SUPERVISOR_MATERIAL_SENTINEL="$sentinel_file" \
  PATH="$shim_dir:$PATH" \
  bash .github/scripts/publish-rank.sh "$ranked" "$state_file" > "$tmpdir/${case_name}.out"

  printf '%s\n' "$record_file"
}

assert_gh_count() {
  local record_file="$1"
  local pattern="$2"
  local expected="$3"
  local actual
  actual="$(grep -c -F "$pattern" "$record_file" || true)"
  if [ "$actual" -ne "$expected" ]; then
    echo "FAIL: expected $expected gh invocations matching '$pattern', got $actual" >&2
    cat "$record_file" >&2
    exit 1
  fi
}

# Scenario 1: first dry-run → material changes (no prior fingerprint) → state written.
SUPERVISOR_PUBLISH_DRY_RUN=1 \
SUPERVISOR_PUBLISH_LOG="$log" \
SUPERVISOR_MATERIAL_SENTINEL="$sentinel" \
GH_REPO="$repo" \
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
GH_REPO="$repo" \
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
GH_REPO="$repo" \
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
if GH_TOKEN="" GH_REPO="$repo" \
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
GH_REPO="$repo" \
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
GH_REPO="$repo" \
bash .github/scripts/publish-rank.sh "$action_diff" "$state" >/tmp/publish-sixth.out

if [ "$(cat "$sentinel")" != "true" ]; then
  echo "FAIL: recommended_action change should flip sentinel to 'true'" >&2
  exit 1
fi
if ! jq -e --arg fp "$prev_fp" '.material_fingerprint != $fp' "$state" >/dev/null; then
  echo "FAIL: recommended_action change should produce a new fingerprint" >&2
  exit 1
fi

# Scenario 7: production dedup with 0 open matches creates one issue.
record="$(run_production_dedup_case "prod-zero-matches" '[]')"
assert_gh_count "$record" "issue create" 1
assert_gh_count "$record" "issue edit" 0
assert_gh_count "$record" "issue close" 0

# Scenario 8: production dedup with 1 open match edits the existing issue.
record="$(run_production_dedup_case "prod-one-match" '[{"number":42,"title":"supervisor-rank: top pipeline clogs","url":"https://github.com/atvirokodosprendimai/ai-pipeline-template/issues/42"}]')"
assert_gh_count "$record" "issue create" 0
assert_gh_count "$record" "issue edit 42" 1
assert_gh_count "$record" "issue close" 0

# Scenario 9: production dedup with 3 open matches reconciles to the lowest issue number.
record="$(run_production_dedup_case "prod-three-matches" '[{"number":37,"title":"supervisor-rank: top pipeline clogs","url":"https://github.com/atvirokodosprendimai/ai-pipeline-template/issues/37"},{"number":10,"title":"supervisor-rank: top pipeline clogs","url":"https://github.com/atvirokodosprendimai/ai-pipeline-template/issues/10"},{"number":22,"title":"supervisor-rank: top pipeline clogs","url":"https://github.com/atvirokodosprendimai/ai-pipeline-template/issues/22"}]')"
assert_gh_count "$record" "issue create" 0
assert_gh_count "$record" "issue edit 10" 1
assert_gh_count "$record" "issue close 22" 1
assert_gh_count "$record" "issue close 37" 1

echo "PASS test-publish: 9 scenarios"
