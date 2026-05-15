#!/usr/bin/env bash
set -euo pipefail

TAXONOMY_FILE="${TAXONOMY_FILE:-company/pipeline-stages.json}"
INPUT="${1:-}"

# Buffer stdin to a tempfile so the input can be validated then re-read.
if [ -z "$INPUT" ] || [ "$INPUT" = "-" ] || [ "$INPUT" = "/dev/stdin" ]; then
  INPUT="$(mktemp)"
  trap 'rm -f "$INPUT"' EXIT
  cat > "$INPUT"
fi

if [ ! -f "$TAXONOMY_FILE" ]; then
  echo "error: missing taxonomy file: $TAXONOMY_FILE" >&2
  exit 1
fi

if ! jq empty "$TAXONOMY_FILE" >/dev/null 2>&1; then
  echo "error: malformed pipeline-stages.json: $TAXONOMY_FILE" >&2
  exit 1
fi

if ! jq empty "$INPUT" >/dev/null 2>&1; then
  echo "error: malformed ranked JSON: $INPUT" >&2
  exit 1
fi

missing_stages="$(jq -r --slurpfile taxonomy "$TAXONOMY_FILE" '
  [.top[]?.stage | select(($taxonomy[0].recommended_actions[.] // null) == null)] | unique | .[]
' "$INPUT")"
if [ -n "$missing_stages" ]; then
  while IFS= read -r stage; do
    [ -n "$stage" ] && echo "warning: no recommended action for stage: $stage" >&2
  done <<< "$missing_stages"
fi

jq --slurpfile taxonomy "$TAXONOMY_FILE" '
  .top = [
    .top[]?
    | (.stage // "unknown") as $stage
    | ($taxonomy[0].recommended_actions[$stage] // null) as $action
    | . + {
        recommended_action: (
          if ($action != null and (($taxonomy[0].allowed_actions // []) | index($action)) != null) then $action
          else null
          end
        )
      }
  ]
' "$INPUT"
