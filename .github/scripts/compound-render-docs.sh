#!/usr/bin/env bash
set -euo pipefail

# Input $1 = path to LLM JSON response file
# Expects JSON array of {category, slug, title, tags:[...], date, markdown}
# Validates category is one of: integration-issues, logic-errors, design-decisions, runtime-errors
# Writes docs/solutions/<category>/<slug>.md with proper frontmatter then markdown body
# Strips slug to [a-z0-9-] only (refuse path traversal)
# Prints list of files written
# Skips + warns on invalid category or unsafe slug

input_path="${1:?usage: compound-render-docs.sh <llm-json-response>}"
tmp_array="$(mktemp)"
tmp_content="$(mktemp)"
trap 'rm -f "$tmp_array" "$tmp_content"' EXIT

if jq -e 'type == "array"' "$input_path" >/dev/null; then
  jq '.' "$input_path" > "$tmp_array"
else
  jq -r '.choices[0].message.content // empty' "$input_path" > "$tmp_content"
  # shellcheck disable=SC2016
  sed -n '/^```json[[:space:]]*$/,/^```[[:space:]]*$/p' "$tmp_content" | sed '1d;$d' > "$tmp_array"
  if ! jq -e 'type == "array"' "$tmp_array" >/dev/null 2>&1; then
    jq -e 'type == "array"' "$tmp_content" >/dev/null
    jq '.' "$tmp_content" > "$tmp_array"
  fi
fi

if ! jq -e 'type == "array"' "$tmp_array" >/dev/null; then
  echo "FAIL: LLM response is not a JSON array" >&2
  exit 1
fi

jq -c '.[]' "$tmp_array" | while IFS= read -r entry; do
  category="$(printf '%s\n' "$entry" | jq -r '.category // ""')"
  slug="$(printf '%s\n' "$entry" | jq -r '.slug // ""')"

  case "$category" in
    integration-issues|logic-errors|design-decisions|runtime-errors) ;;
    *)
      echo "WARN: skipping invalid category: $category" >&2
      continue
      ;;
  esac

  safe_slug="$(printf '%s' "$slug" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]//g')"
  if [[ -z "$safe_slug" || "$slug" != "$safe_slug" ]]; then
    echo "WARN: skipping unsafe slug: $slug" >&2
    continue
  fi

  out_dir="docs/solutions/$category"
  out_file="$out_dir/$safe_slug.md"
  mkdir -p "$out_dir"

  title="$(printf '%s\n' "$entry" | jq -r '.title // ""')"
  date="$(printf '%s\n' "$entry" | jq -r '.date // ""')"
  tags_line="$(printf '%s\n' "$entry" | jq -r '(.tags // []) | map(tostring) | "tags: [" + join(", ") + "]"')"
  markdown="$(printf '%s\n' "$entry" | jq -r '.markdown // ""')"
  title="${title//$'\r'/ }"
  title="${title//$'\n'/ }"
  if ! [[ "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    date=$(date -u +%F)
  fi

  {
    echo "---"
    printf 'title: "%s"\n' "${title//\"/\\\"}"
    printf 'category: %s\n' "$category"
    printf 'date: %s\n' "$date"
    printf '%s\n' "$tags_line"
    echo "---"
    echo
    printf '%s\n' "$markdown"
  } > "$out_file"

  printf '%s\n' "$out_file"
done
