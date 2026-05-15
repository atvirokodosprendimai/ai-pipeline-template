#!/usr/bin/env bash
set -euo pipefail

TARGET_REPOS="${TARGET_REPOS:-atvirokodosprendimai/ai-pipeline-template,atvirokodosprendimai/wgmesh}"

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh CLI is required" >&2
  exit 1
fi

if [ -z "${GH_TOKEN:-}" ]; then
  echo "error: GH_TOKEN is required" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

idx=0
IFS=',' read -r -a repos <<< "$TARGET_REPOS"
for repo in "${repos[@]}"; do
  repo="${repo#"${repo%%[![:space:]]*}"}"
  repo="${repo%"${repo##*[![:space:]]}"}"
  [ -n "$repo" ] || continue

  prs_file="$tmpdir/prs-$idx.json"
  issues_file="$tmpdir/issues-$idx.json"
  combined_file="$tmpdir/combined-$idx.json"

  gh pr list --repo "$repo" --state open --limit 100 \
    --json number,title,labels,createdAt,updatedAt,isDraft,reviewDecision,mergeStateStatus,url \
    > "$prs_file"

  gh issue list --repo "$repo" --state open --limit 100 \
    --json number,title,labels,createdAt,updatedAt,url \
    > "$issues_file"

  jq --arg repo "$repo" '
    [
      (.[0][] | {
        repo: $repo,
        type: "pr",
        number,
        title,
        labels,
        created_at: .createdAt,
        updated_at: .updatedAt,
        is_draft: .isDraft,
        review_decision: .reviewDecision,
        merge_state_status: .mergeStateStatus,
        url
      }),
      (.[1][] | {
        repo: $repo,
        type: "issue",
        number,
        title,
        labels,
        created_at: .createdAt,
        updated_at: .updatedAt,
        is_draft: false,
        url
      })
    ]
  ' "$prs_file" "$issues_file" > "$combined_file"
  idx=$((idx + 1))
done

jq -s 'add // []' "$tmpdir"/combined-*.json
