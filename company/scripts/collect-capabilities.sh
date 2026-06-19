#!/usr/bin/env bash
# Collect already-shipped capabilities for the company control loop.
# Reads recent merged implementation PRs plus docs/solutions/ entries,
# reconciles Revert PRs, and outputs budget-aware text to stdout.
# Output: plain-text capabilities digest to stdout.
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
TARGET_REPO="${TARGET_REPO:-${GITHUB_REPOSITORY:-}}"

BUDGET=4096
LIMIT=200
PR_LIST_FILE=""
SOLUTIONS_DIR="$ROOT/docs/solutions"
SENTINEL="(capabilities digest unavailable this run)"

warn() {
  echo "::warning::collect-capabilities: $*" >&2
}

# -- Parse args ---------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --budget)        BUDGET="$2"; shift 2 ;;
    --limit)         LIMIT="$2"; shift 2 ;;
    --pr-list-file)  PR_LIST_FILE="$2"; shift 2 ;;
    --solutions-dir) SOLUTIONS_DIR="$2"; shift 2 ;;
    *) warn "Unknown option: $1"; shift ;;
  esac
done

fetch_prs() {
  if [ -n "$PR_LIST_FILE" ]; then
    if [ ! -s "$PR_LIST_FILE" ]; then
      warn "PR list file missing or empty: $PR_LIST_FILE"
      return 1
    fi
    cat "$PR_LIST_FILE" || return 1
    return 0
  fi

  if [ -z "$TARGET_REPO" ]; then
    warn "TARGET_REPO/GITHUB_REPOSITORY not set"
    return 1
  fi

  gh pr list \
    --repo "$TARGET_REPO" \
    --state merged \
    --limit "$LIMIT" \
    --json number,title,body 2>/dev/null || {
      warn "gh pr list failed for $TARGET_REPO"
      return 1
    }
}

parse_prs() {
  jq -r '
    def strip_prefix:
      sub("^(feat|fix|refactor|perf|chore|docs|ci|test|style|build)(\\([^)]*\\))?:\\s*"; ""; "i");
    def trim:
      gsub("^\\s+|\\s+$"; "");
    def summary:
      ((.body // "")
        | split("\n")
        | map(trim)
        | map(select(length > 0))
        | .[0] // "")
      | if length > 100 then .[0:100] + "..." else . end;
    def capability_line:
      (.title | strip_prefix) as $title
      | summary as $summary
      | $title + " (PR #" + (.number | tostring) + ")"
        + (if $summary == "" then "" else " — " + $summary end);

    if type != "array" then
      error("expected PR JSON array")
    else
      . as $prs
      | [
          $prs[]
          | (.title // "")
          | capture("^Revert \"(?<inner>.*)\"$"; "i")?
          | .inner
          | strip_prefix
        ] as $reverted_titles
      | [
          $prs[]
          | select((.title // "" | test("^(chore|docs|ci|test|style|build)(\\([^)]*\\))?:\\s*"; "i")) | not)
          | select((.title // "" | test("^Revert \""; "i")) | not)
          | (.title | strip_prefix) as $capability_title
          | select(($reverted_titles | index($capability_title)) | not)
          | {key: $capability_title, line: capability_line}
        ]
      | reduce .[] as $item (
          {seen: {}, lines: []};
          if .seen[$item.key] then
            .
          else
            .seen[$item.key] = true | .lines += [$item.line]
          end
        )
      | .lines[]
    end
  ' 2>/dev/null
}

solution_title() {
  local file="$1"
  awk '
    BEGIN { in_frontmatter = 0 }
    NR == 1 && /^---$/ { in_frontmatter = 1; next }
    in_frontmatter && /^---$/ { in_frontmatter = 0; next }
    in_frontmatter && /^title:[[:space:]]*/ {
      line = $0
      sub(/^title:[[:space:]]*/, "", line)
      gsub(/^["\047]|["\047]$/, "", line)
      print line
      exit
    }
    !in_frontmatter && /^# / {
      line = $0
      sub(/^# /, "", line)
      print line
      exit
    }
  ' "$file" 2>/dev/null || true
}

collect_solutions() {
  if [ ! -d "$SOLUTIONS_DIR" ]; then
    return 0
  fi

  while IFS= read -r file; do
    [ -n "$file" ] || continue
    title=$(solution_title "$file")
    [ -n "$title" ] || continue
    if [ "${#title}" -gt 160 ]; then
      title="${title:0:160}..."
    fi
    printf '%s\n' "$title"
  done < <(find "$SOLUTIONS_DIR" -type f -name '*.md' | sort)
}

dedup_lines() {
  awk 'NF && !seen[$0]++'
}

apply_budget() {
  local total=0
  local line
  local bytes

  while IFS= read -r line; do
    [ -n "$line" ] || continue
    bytes=$(printf '%s\n' "$line" | wc -c | tr -d ' ')
    if [ $((total + bytes)) -le "$BUDGET" ]; then
      printf '%s\n' "$line"
      total=$((total + bytes))
    else
      break
    fi
  done
}

main() {
  local pr_json
  local pr_lines=""
  local solution_lines=""
  local output=""

  if ! pr_json=$(fetch_prs); then
    echo "$SENTINEL"
    return 0
  fi

  if ! pr_lines=$(printf '%s\n' "$pr_json" | parse_prs); then
    warn "failed to parse PR JSON"
    echo "$SENTINEL"
    return 0
  fi

  solution_lines=$(collect_solutions || true)
  output=$(printf '%s\n%s\n' "$pr_lines" "$solution_lines" | dedup_lines | apply_budget)

  if [ -z "$output" ]; then
    warn "no capabilities found"
    echo "$SENTINEL"
    return 0
  fi

  printf '%s\n' "$output"
}

main
