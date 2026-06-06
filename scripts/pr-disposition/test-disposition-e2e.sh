#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

mkdir -p "$TMPDIR/bin"
export PATH="$TMPDIR/bin:$PATH"
export OPENROUTER_API_KEY="test-key"
export PR_DISPOSITION_STATE="$TMPDIR/state.json"
printf '{"ledger":[],"acted_fingerprints":[]}\n' > "$PR_DISPOSITION_STATE"

cat > "$TMPDIR/bin/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "pr" && "$2" == "list" ]]; then
  cat <<'JSON'
[{"number":101,"headRefOid":"sha-merge-low"},{"number":102,"headRefOid":"sha-merge-high"},{"number":103,"headRefOid":"sha-stale"},{"number":104,"headRefOid":"sha-conflict-low"},{"number":105,"headRefOid":"sha-conflict-high"},{"number":106,"headRefOid":"sha-human"},{"number":107,"headRefOid":"sha-leave"},{"number":108,"headRefOid":"sha-current"}]
JSON
  exit 0
fi
if [[ "$1" == "pr" && "$2" == "view" ]]; then
  pr="$3"
  if [[ "$*" == *"--jq .headRefOid"* ]]; then
    case "$pr" in
      101) echo "sha-merge-low" ;;
      102) echo "sha-merge-high" ;;
      103) echo "sha-stale" ;;
      104) echo "sha-conflict-low" ;;
      105) echo "sha-conflict-high" ;;
      106) echo "sha-human" ;;
      107) echo "sha-leave" ;;
      108) echo "sha-current" ;;
      *) exit 1 ;;
    esac
    exit 0
  fi
  case "$pr" in
    101) cat <<'JSON'
{"number":101,"title":"Merge low","mergeable":"MERGEABLE","headRefOid":"sha-merge-low","labels":[],"author":{"login":"operator"},"files":[{"path":"scripts/a.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"Copilot"},"state":"COMMENTED","body":"CLEAN","commit":{"oid":"sha-merge-low"}}]}
JSON
      ;;
    102) cat <<'JSON'
{"number":102,"title":"Merge high","mergeable":"MERGEABLE","headRefOid":"sha-merge-high","labels":[],"author":{"login":"operator"},"files":[{"path":"docs/customers/acme.md"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"Copilot"},"state":"COMMENTED","body":"CLEAN","commit":{"oid":"sha-merge-high"}}]}
JSON
      ;;
    103) cat <<'JSON'
{"number":103,"title":"Superseded stale","mergeable":"MERGEABLE","headRefOid":"sha-stale","labels":[],"author":{"login":"operator"},"files":[{"path":"scripts/stale.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"FAILURE"}],"reviews":[]}
JSON
      ;;
    104) cat <<'JSON'
{"number":104,"title":"Conflict low","mergeable":"CONFLICTING","headRefOid":"sha-conflict-low","labels":[],"author":{"login":"operator"},"files":[{"path":"scripts/conflict.sh"}],"statusCheckRollup":[],"reviews":[]}
JSON
      ;;
    105) cat <<'JSON'
{"number":105,"title":"Conflict high","mergeable":"CONFLICTING","headRefOid":"sha-conflict-high","labels":[],"author":{"login":"operator"},"files":[{"path":"company/system-prompt.md"}],"statusCheckRollup":[],"reviews":[]}
JSON
      ;;
    106) cat <<'JSON'
{"number":106,"title":"Human","mergeable":"MERGEABLE","headRefOid":"sha-human","labels":[{"name":"needs-human"}],"author":{"login":"operator"},"files":[{"path":"scripts/human.sh"}],"statusCheckRollup":[],"reviews":[]}
JSON
      ;;
    107) cat <<'JSON'
{"number":107,"title":"Still wanted","mergeable":"MERGEABLE","headRefOid":"sha-leave","labels":[],"author":{"login":"operator"},"files":[{"path":"scripts/leave.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"FAILURE"}],"reviews":[]}
JSON
      ;;
    108) cat <<'JSON'
{"number":108,"title":"Stale Copilot SHA","mergeable":"MERGEABLE","headRefOid":"sha-current","labels":[],"author":{"login":"operator"},"files":[{"path":"scripts/old-review.sh"}],"statusCheckRollup":[{"name":"ci","status":"COMPLETED","conclusion":"SUCCESS"}],"reviews":[{"author":{"login":"Copilot"},"state":"COMMENTED","body":"CLEAN","commit":{"oid":"sha-old"}}]}
JSON
      ;;
    *) exit 1 ;;
  esac
  exit 0
fi
printf '%s\n' "$*" >> "$GH_LOG"
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
if grep -q "Superseded stale" "$request"; then
  content='{"verdict":"stale","reason":"A newer PR supersedes this work."}'
else
  content='{"verdict":"leave","reason":"The PR still appears wanted."}'
fi
jq -n --arg content "$content" '{choices:[{message:{content:$content}}]}' > "$out"
printf '200'
SH
chmod +x "$TMPDIR/bin/curl"

record_fingerprint() {
  local fingerprint="$1"
  local tmp
  tmp="$(mktemp)"
  jq --arg fp "$fingerprint" \
    '.acted_fingerprints = ((.acted_fingerprints // []) + [$fp] | unique)' \
    "$PR_DISPOSITION_STATE" > "$tmp"
  bash "$ROOT_DIR/company/scripts/sanitise.sh" < "$tmp" >/dev/null
  mv "$tmp" "$PR_DISPOSITION_STATE"
}

has_fingerprint() {
  local fingerprint="$1"
  jq -e --arg fp "$fingerprint" '(.acted_fingerprints // []) | index($fp) != null' "$PR_DISPOSITION_STATE" >/dev/null
}

run_queue() {
  local dry_run="$1"
  while IFS= read -r pr; do
    [[ -n "$pr" ]] || continue
    local classification class sha fp comment tmp
    classification="$(bash "$ROOT_DIR/scripts/pr-disposition/classify.sh" "$pr")"
    class="$(jq -r '.class' <<< "$classification")"
    sha="$(gh pr view "$pr" --json headRefOid --jq .headRefOid)"
    fp="${pr}:${sha}:${class}"
    if has_fingerprint "$fp"; then
      echo "skip ${fp}"
      continue
    fi
    case "$class" in
      stale)
        if [[ "$dry_run" == "true" ]]; then
          echo "DRY_RUN stale ${pr}"
        else
          bash "$ROOT_DIR/scripts/pr-disposition/close-stale.sh" "$pr" "$classification"
          record_fingerprint "$fp"
        fi
        ;;
      human)
        if [[ "$dry_run" == "true" ]]; then
          echo "DRY_RUN human ${pr}"
        else
          comment="$(jq -r '.reasons | join("; ")' <<< "$classification")"
          comment="PR disposition escalated for human review: ${comment}"
          bash "$ROOT_DIR/company/scripts/sanitise.sh" <<< "$comment" >/dev/null
          gh pr edit "$pr" --add-label needs-human
          gh pr comment "$pr" --body "$comment"
          record_fingerprint "$fp"
        fi
        ;;
      merge-low|merge-high|conflict-low|conflict-high)
        echo "DRY_RUN ${class} ${pr}"
        ;;
      leave)
        :
        ;;
      *)
        echo "unknown class ${class}" >&2
        exit 1
        ;;
    esac
  done < <(gh pr list --state open --json number,headRefOid | jq -r '.[].number')
}

pass=0
total=0

assert_log_contains() {
  local name="$1" needle="$2"
  total=$((total + 1))
  if grep -qF -- "$needle" "$GH_LOG"; then
    pass=$((pass + 1))
  else
    echo "FAIL ${name}: missing ${needle}" >&2
    cat "$GH_LOG" >&2 || true
    exit 1
  fi
}

assert_log_not_contains() {
  local name="$1" needle="$2"
  total=$((total + 1))
  if ! grep -qF -- "$needle" "$GH_LOG" 2>/dev/null; then
    pass=$((pass + 1))
  else
    echo "FAIL ${name}: unexpected ${needle}" >&2
    cat "$GH_LOG" >&2
    exit 1
  fi
}

assert_output_contains() {
  local name="$1" needle="$2" file="$3"
  total=$((total + 1))
  if grep -qF -- "$needle" "$file"; then
    pass=$((pass + 1))
  else
    echo "FAIL ${name}: missing ${needle}" >&2
    cat "$file" >&2
    exit 1
  fi
}

assert_jq() {
  local name="$1" expr="$2"
  total=$((total + 1))
  if jq -e "$expr" "$PR_DISPOSITION_STATE" >/dev/null; then
    pass=$((pass + 1))
  else
    echo "FAIL ${name}: jq ${expr}" >&2
    cat "$PR_DISPOSITION_STATE" >&2
    exit 1
  fi
}

export GH_LOG="$TMPDIR/gh.log"
: > "$GH_LOG"
run_queue false > "$TMPDIR/run1.out"
assert_log_contains "stale is closed" "pr close 103 --comment"
assert_log_contains "human gets needs-human label" "pr edit 106 --add-label needs-human"
assert_log_not_contains "no merge command" "pr merge"
assert_log_not_contains "no edit merge command" "--merge"
assert_output_contains "merge-low print only" "DRY_RUN merge-low 101" "$TMPDIR/run1.out"
assert_output_contains "merge-high print only" "DRY_RUN merge-high 102" "$TMPDIR/run1.out"
assert_output_contains "conflict-low print only" "DRY_RUN conflict-low 104" "$TMPDIR/run1.out"
assert_output_contains "conflict-high print only" "DRY_RUN conflict-high 105" "$TMPDIR/run1.out"
leave_json="$(bash "$ROOT_DIR/scripts/pr-disposition/classify.sh" 108)"
total=$((total + 1))
if [[ "$(jq -r '.class' <<< "$leave_json")" == "leave" ]]; then
  pass=$((pass + 1))
else
  echo "FAIL stale Copilot SHA classified as merge: ${leave_json}" >&2
  exit 1
fi
assert_jq "stale fingerprint recorded" '(.acted_fingerprints // []) | index("103:sha-stale:stale") != null'
assert_jq "human fingerprint recorded" '(.acted_fingerprints // []) | index("106:sha-human:human") != null'

before="$(wc -l < "$GH_LOG" | tr -d ' ')"
run_queue false > "$TMPDIR/run2.out"
after="$(wc -l < "$GH_LOG" | tr -d ' ')"
total=$((total + 1))
if [[ "$before" == "$after" ]]; then
  pass=$((pass + 1))
else
  echo "FAIL idempotency: expected no second-run mutations" >&2
  exit 1
fi

printf '{"ledger":[],"acted_fingerprints":[]}\n' > "$PR_DISPOSITION_STATE"
: > "$GH_LOG"
run_queue true > "$TMPDIR/dry.out"
assert_log_not_contains "dry run has no close" "pr close"
assert_log_not_contains "dry run has no edit" "pr edit"
assert_log_not_contains "dry run has no comment" "pr comment"
assert_jq "dry run leaves state empty" '(.ledger | length == 0) and (.acted_fingerprints | length == 0)'

echo "PASS ${pass}/${total}"
