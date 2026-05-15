#!/usr/bin/env bash
set -euo pipefail

TAXONOMY_FILE="${TAXONOMY_FILE:-company/pipeline-stages.json}"
INPUT="${1:-}"
NOW="${SUPERVISOR_NOW:-$(date -u '+%Y-%m-%dT%H:%M:%SZ')}"

# Buffer stdin to a tempfile so the input can be validated then re-read.
# /dev/stdin is not seekable; without this the second jq sees EOF and emits empty output.
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

if ! jq -e '
  . as $root
  |
  (.stages | type == "array")
  and (.classification_rules | type == "object")
  and (.dwell_thresholds_hours | type == "object")
  and (.recommended_actions | type == "object")
  and (all(.stages[]; (. as $stage | type == "string" and ($root.classification_rules[$stage] | type == "object"))))
' "$TAXONOMY_FILE" >/dev/null; then
  echo "error: bad rule in pipeline-stages.json: missing stage classification rule" >&2
  exit 1
fi

if ! jq empty "$INPUT" >/dev/null 2>&1; then
  echo "error: malformed snapshot JSON: $INPUT" >&2
  exit 1
fi

jq --arg now "$NOW" --slurpfile taxonomy "$TAXONOMY_FILE" '
  def label_names($item): [($item.labels // [])[]?.name];
  def has_label($item; $name): label_names($item) | index($name) != null;
  def has_any_label($item; $names): any($names[]?; has_label($item; .));
  def title_starts($item; $prefixes):
    ($item.title // "" | ascii_downcase) as $title
    | any($prefixes[]?; . as $prefix | ($title | startswith($prefix | ascii_downcase)));
  def has_type_label($item): any(label_names($item)[]?; startswith("type:"));
  def rule($stage): $taxonomy[0].classification_rules[$stage] // {};
  def matches($item; $stage):
    (rule($stage)) as $rule
    | (
        has_any_label($item; $rule.label_any // [])
        or title_starts($item; $rule.title_prefix_any // [])
        or (
          (($rule.review_decision_any // []) | length) > 0
          and (($item.review_decision // "") as $decision | ($rule.review_decision_any | index($decision)) != null)
          and (
            (($rule.merge_state_status_any // []) | length) == 0
            or (($item.merge_state_status // "") as $status | ($rule.merge_state_status_any | index($status)) != null)
          )
        )
        or (
          ($stage == "triage")
          and ($item.type == "issue")
          and (($rule.issue_without_type_label // false) == true)
          and (has_type_label($item) | not)
          and ((label_names($item) | length) == 0)
        )
      );
  def stage($item):
    if has_label($item; "needs-human") then "review"
    elif (($item.title // "" | ascii_downcase) | startswith("spec:")) then "spec"
    elif ($item.type == "pr" and (($item.review_decision // "") == "APPROVED") and ((($item.merge_state_status // "") == "CLEAN") or (($item.merge_state_status // "") == "HAS_HOOKS"))) then "merge"
    elif matches($item; "revenue") then "revenue"
    elif matches($item; "verify") then "verify"
    elif matches($item; "review") then "review"
    elif matches($item; "build") then "build"
    elif matches($item; "spec") then "spec"
    elif matches($item; "triage") then "triage"
    else "unknown"
    end;
  def dwell_start($item; $stage):
    if $stage == "triage" and has_label($item; "copilot-triaging") then ($item.updated_at // $item.updatedAt // $item.created_at // $item.createdAt)
    else ($item.created_at // $item.createdAt // $item.updated_at // $item.updatedAt)
    end;
  map(
    . as $item
    | (stage($item)) as $stage
    | (dwell_start($item; $stage)) as $start
    | . + {
        stage: $stage,
        dwell_hours: (
          if ($start == null or $start == "") then 0
          else (((($now | fromdateiso8601) - ($start | fromdateiso8601)) / 3600) | floor | if . < 0 then 0 else . end)
          end
        )
      }
  )
' "$INPUT"
