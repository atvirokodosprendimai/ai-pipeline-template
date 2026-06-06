#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

mkdir -p "$TMPDIR/bin"
export PATH="$TMPDIR/bin:$PATH"
export OPENROUTER_API_KEY="test-key"

cat > "$TMPDIR/bin/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "pr" && "$2" == "view" ]]; then
  pr="$3"
  case "$pr" in
    1) cat <<'JSON'
{"number":1,"title":"Low clean","mergeable":"MERGEABLE","headRefOid":"sha-low","author":{"login":"operator"},"labels":[],"files":[{"path":"docs/notes.md"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"Copilot"},"state":"COMMENTED","body":"CLEAN","commit":{"oid":"sha-low"}}]}
JSON
      ;;
    2) cat <<'JSON'
{"number":2,"title":"High clean","mergeable":"MERGEABLE","headRefOid":"sha-high","author":{"login":"operator"},"labels":[],"files":[{"path":"docs/customers/acme.md"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"copilot-swe-agent[bot]"},"state":"COMMENTED","body":"CLEAN","commit":{"oid":"sha-high"}}]}
JSON
      ;;
    3) cat <<'JSON'
{"number":3,"title":"Superseded by newer PR","mergeable":"MERGEABLE","headRefOid":"sha-stale","author":{"login":"operator"},"labels":[],"files":[{"path":"docs/notes.md"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"FAILURE"}],"reviews":[]}
JSON
      ;;
    4) cat <<'JSON'
{"number":4,"title":"Conflict low","mergeable":"CONFLICTING","headRefOid":"sha-conflict","author":{"login":"operator"},"labels":[],"files":[{"path":"scripts/tool.sh"}],"statusCheckRollup":[],"reviews":[]}
JSON
      ;;
    5) cat <<'JSON'
{"number":5,"title":"Manual","mergeable":"MERGEABLE","headRefOid":"sha-human","author":{"login":"operator"},"labels":[{"name":"needs-human"}],"files":[{"path":"scripts/tool.sh"}],"statusCheckRollup":[],"reviews":[]}
JSON
      ;;
    6) cat <<'JSON'
{"number":6,"title":"Stale Copilot SHA","mergeable":"MERGEABLE","headRefOid":"sha-current","author":{"login":"operator"},"labels":[],"files":[{"path":"scripts/tool.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"Copilot"},"state":"COMMENTED","body":"CLEAN","commit":{"oid":"sha-old"}}]}
JSON
      ;;
    7) cat <<'JSON'
{"number":7,"title":"Conflict high","mergeable":"CONFLICTING","headRefOid":"sha-conflict-high","author":{"login":"operator"},"labels":[],"files":[{"path":"company/system-prompt.md"}],"statusCheckRollup":[],"reviews":[]}
JSON
      ;;
    8) cat <<'JSON'
{"number":8,"title":"Still wanted","mergeable":"MERGEABLE","headRefOid":"sha-leave","author":{"login":"operator"},"labels":[],"files":[{"path":"scripts/tool.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"FAILURE"}],"reviews":[]}
JSON
      ;;
    9) cat <<'JSON'
{"number":9,"title":"Not clean body","mergeable":"MERGEABLE","headRefOid":"sha-not-clean","author":{"login":"operator"},"labels":[],"files":[{"path":"scripts/tool.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"Copilot"},"state":"COMMENTED","body":"NOT CLEAN","commit":{"oid":"sha-not-clean"}}]}
JSON
      ;;
    10) cat <<'JSON'
{"number":10,"title":"First line clean","mergeable":"MERGEABLE","headRefOid":"sha-first-line-clean","author":{"login":"operator"},"labels":[],"files":[{"path":"scripts/tool.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"Copilot"},"state":"COMMENTED","body":"  CLEAN  \nfollow-up text","commit":{"oid":"sha-first-line-clean"}}]}
JSON
      ;;
    11) cat <<'JSON'
{"number":11,"title":"Approved clean","mergeable":"MERGEABLE","headRefOid":"sha-approved","author":{"login":"operator"},"labels":[],"files":[{"path":"scripts/tool.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"Copilot"},"state":"APPROVED","body":"NOT CLEAN","commit":{"oid":"sha-approved"}}]}
JSON
      ;;
    12) cat <<'JSON'
{"number":12,"title":"Stale approved clean","mergeable":"MERGEABLE","headRefOid":"sha-current-approved","author":{"login":"operator"},"labels":[],"files":[{"path":"scripts/tool.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"Copilot"},"state":"APPROVED","body":"  CLEAN  ","commit":{"oid":"sha-old-approved"}}]}
JSON
      ;;
    *) exit 1 ;;
  esac
  exit 0
fi
exit 1
SH
chmod +x "$TMPDIR/bin/gh"

cat > "$TMPDIR/bin/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out=""
request=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -d)
      if [[ "$2" == @* ]]; then request="${2#@}"; fi
      shift 2
      ;;
    *) shift ;;
  esac
done
user_content="$(jq -r '.messages[] | select(.role == "user").content' "$request")"
if grep -Eq 'statusCheckRollup|reviews|"body"|"commit"' <<< "$user_content"; then
  echo "LLM request leaked full PR details" >&2
  exit 1
fi
if grep -q "Superseded" "$request"; then
  content='{"verdict":"stale","reason":"A newer PR supersedes this implementation."}'
else
  content='{"verdict":"leave","reason":"The PR still appears wanted."}'
fi
jq -n --arg content "$content" '{choices:[{message:{content:$content}}]}' > "$out"
printf '200'
SH
chmod +x "$TMPDIR/bin/curl"

pass=0
total=0

assert_class() {
  local pr="$1" expected_class="$2" expected_tier="$3" reason_fragment="${4:-}"
  total=$((total + 1))
  local out actual_class actual_tier
  out=$(bash "$ROOT_DIR/scripts/pr-disposition/classify.sh" "$pr")
  jq empty <<< "$out"
  actual_class=$(jq -r '.class' <<< "$out")
  actual_tier=$(jq -r '.risk_tier' <<< "$out")
  if [[ "$actual_class" != "$expected_class" || "$actual_tier" != "$expected_tier" ]]; then
    echo "FAIL PR ${pr}: expected ${expected_class}/${expected_tier}, got ${actual_class}/${actual_tier}: ${out}" >&2
    exit 1
  fi
  if [[ -n "$reason_fragment" ]] && ! jq -e --arg frag "$reason_fragment" '.reasons[] | contains($frag)' <<< "$out" >/dev/null; then
    echo "FAIL PR ${pr}: missing reason fragment ${reason_fragment}: ${out}" >&2
    exit 1
  fi
  pass=$((pass + 1))
}

assert_class 1 "merge-low" "low"
assert_class 2 "merge-high" "high"
assert_class 3 "stale" "low" "newer PR"
assert_class 4 "conflict-low" "low"
assert_class 5 "human" "low" "needs-human"
assert_class 6 "leave" "low" "stale-copilot-sha"
assert_class 7 "conflict-high" "high"
assert_class 8 "leave" "low" "still appears wanted"
assert_class 9 "leave" "low" "still appears wanted"
assert_class 10 "merge-low" "low"
assert_class 11 "merge-low" "low"
assert_class 12 "leave" "low" "stale-copilot-sha"

echo "PASS ${pass}/${total}"
