#!/usr/bin/env bash
# Collect contribution signals for the company control loop.
# Reads git log and existing contributor ledger.
# Output: JSON to stdout.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Recent git contributors (last 7 days)
since=$(date -u -v-7d '+%Y-%m-%d' 2>/dev/null || date -u -d '7 days ago' '+%Y-%m-%d' 2>/dev/null || echo "1970-01-01")
recent_authors=$(git log --since="$since" --format='%aN' 2>/dev/null | sort -u | jq -R . | jq -s . 2>/dev/null || echo '[]')

# AI agent activity (count commits by bots in last 7 days)
bot_commits=$(git log --since="$since" --format='%aN' 2>/dev/null | { grep -ciE 'copilot|goose|github-actions|bot' || true; })

# Dependency count (language-agnostic: try common manifest files)
direct_dep_count=0
if [ -f "$REPO_ROOT/go.mod" ]; then
  indirect=$(grep -cE '^\t[a-z].*// indirect$' "$REPO_ROOT/go.mod" 2>/dev/null | tr -d '[:space:]' || echo 0)
  total=$(grep -cE '^\t[a-z]' "$REPO_ROOT/go.mod" 2>/dev/null | tr -d '[:space:]' || echo 0)
  direct_dep_count=$(( ${total:-0} - ${indirect:-0} ))
elif [ -f "$REPO_ROOT/package.json" ]; then
  direct_dep_count=$(jq '[.dependencies // {} | keys | length, .devDependencies // {} | keys | length] | add' "$REPO_ROOT/package.json" 2>/dev/null || echo 0)
elif [ -f "$REPO_ROOT/requirements.txt" ]; then
  direct_dep_count=$(grep -cE '^[a-zA-Z]' "$REPO_ROOT/requirements.txt" 2>/dev/null || echo 0)
elif [ -f "$REPO_ROOT/Cargo.toml" ]; then
  direct_dep_count=$(grep -cE '^\w' "$REPO_ROOT/Cargo.toml" 2>/dev/null | head -1 || echo 0)
fi

# Unreciprocated count from ledger
unreciprocated=0
if [ -f "$REPO_ROOT/company/contributors.json" ]; then
  unreciprocated=$(jq '.unreciprocated | length' "$REPO_ROOT/company/contributors.json" 2>/dev/null || echo 0)
fi

# Build JSON safely with jq
jq -n \
  --arg collected_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --argjson recent_authors "$recent_authors" \
  --argjson bot_commits "${bot_commits:-0}" \
  --argjson direct_deps "${direct_dep_count:-0}" \
  --argjson unreciprocated "${unreciprocated:-0}" \
  '{
    source: "contributions",
    collected_at: $collected_at,
    recent_git_authors_7d: $recent_authors,
    bot_commits_7d: $bot_commits,
    direct_dependencies: $direct_deps,
    unreciprocated_count: $unreciprocated
  }'
