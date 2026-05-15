#!/usr/bin/env bash
set -euo pipefail

INPUT="${1:-/dev/stdin}"
TOP_N="${TOP_N:-5}"
NOW="${SUPERVISOR_NOW:-$(date -u '+%Y-%m-%dT%H:%M:%SZ')}"

if ! jq empty "$INPUT" >/dev/null 2>&1; then
  echo "error: malformed classified JSON: $INPUT" >&2
  exit 1
fi

jq --arg now "$NOW" --argjson top_n "$TOP_N" '
  def id: "\(.repo)#\(.number)";
  def stage_summary($items):
    reduce ["triage","spec","build","review","merge","verify","revenue","unknown"][] as $stage
      ({}; .[$stage] = ($items | map(select((.stage // "unknown") == $stage)) | length));
  . as $items
  | [
      $items[]
      | . as $item
      | ($item.stage // "unknown") as $stage
      | (
          if $stage == "spec" then
            ([$items[] | select(.repo == $item.repo and (.stage // "") == "build")] | length | if . < 1 then 1 else . end)
          elif $stage == "triage" then
            ([$items[] | select(.repo == $item.repo and ((.stage // "") == "spec" or (.stage // "") == "build" or (.stage // "") == "review"))] | length | if . < 1 then 1 else . end)
          elif $stage == "merge" then
            ([$items[] | select(.repo == $item.repo and (.stage // "") == "merge")] | length | if . < 1 then 1 else . end)
          elif $stage == "unknown" then 0
          else 1
          end
        ) as $blocked
      | . + {
          id: id,
          downstream_blocked_count: $blocked,
          score: ((.dwell_hours // 0) * $blocked)
        }
    ] as $scored
  | {
      generated_at: $now,
      top: (
        $scored
        | map(select((.stage // "unknown") != "unknown"))
        | sort_by(-(.score // 0), (.created_at // .createdAt // ""), .repo, .number)
        | .[0:$top_n]
        | to_entries
        | map(
            .value
            | {
                rank: (.rank // null),
                id,
                repo,
                type,
                number,
                title,
                stage,
                dwell_hours,
                downstream_blocked_count,
                score
              }
            | .rank = null
          )
        | to_entries
        | map(.value + {rank: (.key + 1)})
      ),
      stage_summary: stage_summary($items),
      unknown: (
        $scored
        | map(select((.stage // "unknown") == "unknown") | {id, repo, type, number, title, stage})
        | sort_by(.repo, .number)
      )
    }
' "$INPUT"
