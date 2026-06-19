#!/usr/bin/env bash
set -euo pipefail

if [ -z "${BASE_SHA:-}" ]; then
  echo "::error::BASE_SHA is required"
  exit 1
fi
if [ -z "${HEAD_SHA:-}" ]; then
  echo "::error::HEAD_SHA is required"
  exit 1
fi

git fetch --no-tags --quiet origin "$BASE_SHA" 2>/dev/null || true

if ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  echo "::error::could not resolve base SHA ${BASE_SHA}"
  exit 1
fi
if ! git cat-file -e "${HEAD_SHA}^{commit}" 2>/dev/null; then
  echo "::error::could not resolve head SHA ${HEAD_SHA}"
  exit 1
fi

shopt -s nocasematch

PATTERN_LABELS=(
  "component-gating pattern"
  "component-gating pattern"
  "component-gating pattern"
  "component-gating pattern"
  "component-gating pattern"
)

PATTERNS=(
  'license[_ -]?(check|key|gate|verification)|check[_ -]?license|verify[_ -]?license|license.*(required|expired|invalid)'
  'trial[_ -]?expired|expire[_ -]?trial|expire[_ -]?trial|trial.*(expire|expiry).*(component|daemon|mesh|routing)'
  '(mesh|daemon|routing).*(pause|stop|disable|halt).*(expir|account|trial|payment)|pause[-_ ]?on[-_ ]?expiry|stop[-_ ]?routing[-_ ]?if[-_ ]?expired|stop[-_ ]?routing'
  'kill[-_ ]?switch|remote[-_ ]?disable|phone[-_ ]?home.*(disable|gate|lock)'
  'pay[-_ ]?to[-_ ]?unlock|feature[-_ ]?gate[-_ ]?on[-_ ]?payment|feature[-_ ]?gate.*payment|account[-_ ]?state.*(gate|gating|disable|lock|pause)|payment[-_ ]?gate|payment.*(gate|gating|unlock|enable)|paywall'
)

fail=0
any_relevant_seen=0
HIT_LABEL=""

gh_escape() {
  local s="$1"
  s="${s//%/%25}"
  s="${s//$'\r'/%0D}"
  s="${s//$'\n'/%0A}"
  s="${s//:/%3A}"
  s="${s//,/%2C}"
  printf '%s' "$s"
}

is_spec_path() {
  local path="$1"
  case "$path" in
    specs/*.md|issues/*.md|docs/specs/*.md|*/specs/*.md|*.spec.md|*-spec.md|*specification*.md)
      return 0
      ;;
  esac
  return 1
}

is_relevant_path() {
  local path="$1"
  if is_spec_path "$path"; then
    return 0
  fi

  case "$path" in
    api/*|app/*|cmd/*|cloudroof/*|daemon/*|internal/*|lib/*|mesh/*|pkg/*|src/*|ui/*|web/*)
      return 0
      ;;
  esac

  return 1
}

line_has_violation() {
  local text="$1"
  local i

  HIT_LABEL=""
  for i in "${!PATTERNS[@]}"; do
    if [[ "$text" =~ ${PATTERNS[$i]} ]]; then
      HIT_LABEL="${PATTERN_LABELS[$i]}"
      return 0
    fi
  done

  return 1
}

emit_violation() {
  local file="$1"
  local line="$2"
  local commit="$3"
  local source="$4"
  local label="$5"
  local escaped_file

  escaped_file="$(gh_escape "$file")"
  fail=1
  if [ "$line" -gt 0 ]; then
    echo "::error file=${escaped_file},line=${line}::commit ${commit:0:7} contains a ${label} in ${source}. This violates the product-values boundary; keep monetization in the managed-service layer."
  else
    echo "::error file=${escaped_file}::commit ${commit:0:7} contains a ${label} in ${source}. This violates the product-values boundary; keep monetization in the managed-service layer."
  fi
}

scan_added_diff_lines() {
  local commit="$1"
  shift
  local files=("$@")
  local diff_tmp
  local current_file=""
  local current_line=0
  local line added

  [ "${#files[@]}" -gt 0 ] || return 0

  diff_tmp="$(mktemp)"
  if ! git show --format= --unified=0 --no-ext-diff --diff-filter=ACMRT -m "$commit" -- "${files[@]}" > "$diff_tmp"; then
    rm -f "$diff_tmp"
    echo "::error::could not inspect diff for commit ${commit}"
    exit 1
  fi

  while IFS= read -r line; do
    if [[ "$line" == "+++ b/"* ]]; then
      current_file="${line#+++ b/}"
      current_line=0
      continue
    fi
    if [[ "$line" == "+++ /dev/null" ]]; then
      current_file=""
      current_line=0
      continue
    fi
    if [[ "$line" =~ ^@@[[:space:]]+-[0-9,]+[[:space:]]+\+([0-9]+)(,[0-9]+)?[[:space:]]@@ ]]; then
      current_line="${BASH_REMATCH[1]}"
      continue
    fi
    if [[ "$line" == +* && "$line" != "+++"* ]]; then
      added="${line#+}"
      if [ -n "$current_file" ] && line_has_violation "$added"; then
        emit_violation "$current_file" "$current_line" "$commit" "added diff line" "$HIT_LABEL"
      fi
      current_line=$((current_line + 1))
      continue
    fi
    if [[ "$line" == " "* ]]; then
      current_line=$((current_line + 1))
    fi
  done < "$diff_tmp"

  rm -f "$diff_tmp"
}

scan_spec_file_at_commit() {
  local commit="$1"
  local file="$2"
  local content_tmp
  local line
  local line_no=0

  if ! git cat-file -e "${commit}:${file}" 2>/dev/null; then
    return 0
  fi

  content_tmp="$(mktemp)"
  if ! git cat-file -p "${commit}:${file}" > "$content_tmp" 2>/dev/null; then
    rm -f "$content_tmp"
    return 0
  fi

  while IFS= read -r line || [ -n "$line" ]; do
    line_no=$((line_no + 1))
    if line_has_violation "$line"; then
      emit_violation "$file" "$line_no" "$commit" "changed spec file" "$HIT_LABEL"
    fi
  done < "$content_tmp"

  rm -f "$content_tmp"
}

mapfile -t commits < <(git rev-list "${BASE_SHA}..${HEAD_SHA}")
if [ "${#commits[@]}" -eq 0 ]; then
  echo "No commits in range. PASS."
  exit 0
fi

echo "Inspecting ${#commits[@]} commit(s) in range ${BASE_SHA:0:7}..${HEAD_SHA:0:7}"

for commit in "${commits[@]}"; do
  mapfile -t commit_files < <(
    git diff-tree --no-commit-id --name-only -r -M -m --diff-filter=ACMRT "$commit" \
      | sort -u \
      || true
  )

  relevant_files=()
  for file in "${commit_files[@]}"; do
    if is_relevant_path "$file"; then
      relevant_files+=("$file")
    fi
  done

  [ "${#relevant_files[@]}" -eq 0 ] && continue
  any_relevant_seen=1

  scan_added_diff_lines "$commit" "${relevant_files[@]}"

  for file in "${relevant_files[@]}"; do
    if is_spec_path "$file"; then
      scan_spec_file_at_commit "$commit" "$file"
    fi
  done
done

if [ "$fail" -ne 0 ]; then
  echo
  echo "Values audit FAILED. Move monetization to the managed-service layer; shipped product components must remain full-functionality."
  exit 1
fi

if [ "$any_relevant_seen" -eq 0 ]; then
  echo "No values-audit relevant paths touched in any commit in range. PASS."
else
  echo "Values audit PASSED across all relevant commits."
fi
