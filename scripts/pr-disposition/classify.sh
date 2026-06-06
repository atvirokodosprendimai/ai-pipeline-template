#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SANITISE="${PR_DISPOSITION_SANITISE:-${ROOT_DIR}/company/scripts/sanitise.sh}"
SYSTEM_PROMPT="${ROOT_DIR}/company/pr-disposition-system-prompt.md"
PR_NUMBER="${1:?usage: classify.sh PR_NUMBER}"
TARGET_REPO="${TARGET_REPO:-${GH_REPO:-}}"
head_sha=""

repo_args=()
if [[ -n "$TARGET_REPO" ]]; then
  repo_args=(--repo "$TARGET_REPO")
fi

emit() {
  local class="$1" risk="$2"
  shift 2
  jq -nc --arg class "$class" --arg risk "$risk" --arg head "$head_sha" --args \
    '{"class": $class, "risk_tier": $risk, "headRefOid": $head, "reasons": $ARGS.positional}' "$@"
}

pr_json=""
if ! pr_json="$(gh pr view "$PR_NUMBER" "${repo_args[@]}" \
  --json number,title,mergeable,statusCheckRollup,reviews,labels,author,files,headRefOid,baseRefName,headRefName,createdAt,updatedAt 2>/dev/null)"; then
  emit "leave" "low" "gh-pr-view-failed"
  exit 0
fi

head_sha="$(jq -r '.headRefOid // ""' <<< "$pr_json")"
mergeable="$(jq -r '.mergeable // "UNKNOWN"' <<< "$pr_json")"
changed_files="$(jq -r '.files[]?.path // empty' <<< "$pr_json")"
risk_tier="$(printf '%s\n' "$changed_files" | bash "${ROOT_DIR}/scripts/pr-disposition/risk-tier.sh")"

if [[ "$mergeable" == "CONFLICTING" ]]; then
  emit "conflict-${risk_tier}" "$risk_tier" "mergeable-CONFLICTING"
  exit 0
fi

if jq -e '[.labels[]?.name // empty] | any(. == "needs-human")' <<< "$pr_json" >/dev/null; then
  emit "human" "$risk_tier" "needs-human-label"
  exit 0
fi

if jq -e '[.labels[]?.name // empty] | any(. == "manual-only")' <<< "$pr_json" >/dev/null; then
  emit "human" "$risk_tier" "manual-only-label"
  exit 0
fi

ci_green="$(jq -r '
  (.statusCheckRollup // []) as $checks
  | if ($checks | length) == 0 then false
    else all($checks[];
      (((.status // .state // "") | ascii_downcase) as $status
      | ((.conclusion // .state // "") | ascii_downcase) as $conclusion
      | (($status == "" or $status == "completed" or $status == "success")
         and ($conclusion == "success" or $conclusion == "neutral" or $conclusion == "skipped"))))
    end
' <<< "$pr_json")"

copilot_state="$(jq -nc --argjson pr "$pr_json" --arg head "$head_sha" '
  def login: (.author.login // .user.login // "");
  def commit_oid: (.commit.oid // .commitOID // .commitId // .commit_id // "");
  def is_copilot: (login | test("copilot"; "i"));
  def first_line_trimmed: ((.body // "") | split("\n")[0] | gsub("^[[:space:]]+|[[:space:]]+$"; ""));
  def is_clean:
    ((((.state // "") | ascii_upcase) == "APPROVED")
     or (first_line_trimmed == "CLEAN"));
  ($pr.reviews // []) as $reviews
  | {
      current_clean: any($reviews[]?; is_copilot and is_clean and commit_oid == $head),
      stale_clean: any($reviews[]?; is_copilot and is_clean and commit_oid != "" and commit_oid != $head)
    }
')"
current_clean="$(jq -r '.current_clean' <<< "$copilot_state")"
stale_clean="$(jq -r '.stale_clean' <<< "$copilot_state")"

if [[ "$ci_green" == "true" && "$current_clean" == "true" ]]; then
  emit "merge-${risk_tier}" "$risk_tier" "mergeable" "ci-green" "copilot-clean-current-head"
  exit 0
fi

if [[ "$stale_clean" == "true" ]]; then
  emit "leave" "$risk_tier" "stale-copilot-sha"
  exit 0
fi

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  emit "leave" "$risk_tier" "no-api-key"
  exit 0
fi

request="$(mktemp)"
response="$(mktemp)"
content_file="$(mktemp)"
trap 'rm -f "$request" "$response" "$content_file"' EXIT

pr_summary="$(jq -c '
  {
    number: .number,
    title: (.title // ""),
    changedFilePaths: [.files[]?.path // empty],
    baseRefName: (.baseRefName // ""),
    headRefName: (.headRefName // ""),
    age: {
      createdAt: (.createdAt // ""),
      updatedAt: (.updatedAt // "")
    },
    labels: [.labels[]?.name // empty]
  }
' <<< "$pr_json")"

jq -n \
  --rawfile system "$SYSTEM_PROMPT" \
  --arg pr_number "$PR_NUMBER" \
  --argjson pr "$pr_summary" \
  --arg risk "$risk_tier" \
  '{
    model: "anthropic/claude-sonnet-4",
    max_tokens: 1024,
    messages: [
      {role: "system", content: $system},
      {role: "user", content: ("Classify PR #" + $pr_number + " for stale-vs-leave only. Risk tier: " + $risk + "\nPR summary:\n" + ($pr | tostring))}
    ]
  }' > "$request"

http_code="$(curl -s -w '%{http_code}' -o "$response" \
  -H "Authorization: Bearer ${OPENROUTER_API_KEY}" \
  -H "content-type: application/json" \
  -d @"$request" \
  https://openrouter.ai/api/v1/chat/completions || true)"

if [[ ! "$http_code" =~ ^2[0-9][0-9]$ ]]; then
  emit "leave" "$risk_tier" "llm-http-${http_code:-failed}"
  exit 0
fi

jq -r '.choices[0].message.content // ""' "$response" > "$content_file"
if ! "$SANITISE" < "$content_file" >/dev/null; then
  emit "leave" "$risk_tier" "llm-sanitise-rejected"
  exit 0
fi

llm_json="$(mktemp)"
trap 'rm -f "$request" "$response" "$content_file" "$llm_json"' EXIT
if jq -e . "$content_file" > "$llm_json" 2>/dev/null; then
  :
else
  sed -n '/^```json[[:space:]]*$/,/^```[[:space:]]*$/p' "$content_file" | sed '1d;$d' > "$llm_json"
fi

if ! jq -e '(.verdict == "stale" or .verdict == "leave") and (.reason | type == "string")' "$llm_json" >/dev/null 2>&1; then
  emit "leave" "$risk_tier" "llm-invalid-json"
  exit 0
fi

verdict="$(jq -r '.verdict' "$llm_json")"
reason="$(jq -r '.reason' "$llm_json")"
if [[ "$verdict" == "stale" ]]; then
  emit "stale" "$risk_tier" "$reason"
else
  emit "leave" "$risk_tier" "$reason"
fi
