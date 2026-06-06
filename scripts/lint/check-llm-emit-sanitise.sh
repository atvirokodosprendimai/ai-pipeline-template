#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"

if [[ ! -d "${ROOT}" ]]; then
  printf 'error: scan root does not exist: %s\n' "${ROOT}" >&2
  exit 2
fi

cd "${ROOT}"

LLM_REGEX='OpenRouter|OBSERVER_API_KEY|goal_sprint|/tmp/[^[:space:]"'"'"']*sprint[^[:space:]"'"'"']*\.json|assessment\.json|-system-prompt\.md'
SINK_REGEX='gh[[:space:]]+issue[[:space:]]+create|gh[[:space:]]+pr[[:space:]]+create|gh[[:space:]]+pr[[:space:]]+comment|gh[[:space:]]+issue[[:space:]]+comment|git[[:space:]]+commit'
EXEMPT_REGEX='^[[:space:]]*#[[:space:]]*sanitise-wall:[[:space:]]*exempt[[:space:]]+(.+)$'

collect_files() {
  if [[ -d .github/workflows ]]; then
    find .github/workflows -maxdepth 1 -type f -name '*.yml' -print
  fi

  if [[ -d company/scripts ]]; then
    find company/scripts -maxdepth 1 -type f -name '*.sh' -print
  fi

  if [[ -d scripts ]]; then
    find scripts -type f -name '*.sh' -print
  fi
}

has_match() {
  local file="$1"
  local regex="$2"

  grep -Eq "${regex}" "${file}"
}

first_sink_line() {
  local file="$1"
  local match

  match="$(grep -nE "${SINK_REGEX}" "${file}" | head -n 1 || true)"
  if [[ -z "${match}" ]]; then
    printf '0\n'
    return
  fi

  printf '%s\n' "${match%%:*}"
}

exempt_reason() {
  local file="$1"
  local line

  line="$(grep -E "${EXEMPT_REGEX}" "${file}" | head -n 1 || true)"
  if [[ -z "${line}" ]]; then
    return 1
  fi

  printf '%s\n' "${line}" | sed -E 's/^[[:space:]]*#[[:space:]]*sanitise-wall:[[:space:]]*exempt[[:space:]]+//'
}

main() {
  local flagged=0
  local exempt=0
  local ok=0
  local file
  local reason
  local sink_line
  local -a files=()

  while IFS= read -r file; do
    files+=("${file#./}")
  done < <(collect_files | sort -u)

  for file in "${files[@]}"; do
    if ! has_match "${file}" "${LLM_REGEX}"; then
      continue
    fi

    if ! has_match "${file}" "${SINK_REGEX}"; then
      continue
    fi

    if reason="$(exempt_reason "${file}")"; then
      exempt=$((exempt + 1))
      printf '[EXEMPT]  %s — reason: %s\n' "${file}" "${reason}"
      continue
    fi

    if has_match "${file}" 'sanitise\.sh'; then
      ok=$((ok + 1))
      printf '[OK]      %s\n' "${file}"
      continue
    fi

    flagged=$((flagged + 1))
    sink_line="$(first_sink_line "${file}")"
    printf '[FLAGGED] %s — sink on line %s\n' "${file}" "${sink_line}"
  done

  printf 'Summary: %s flagged, %s exempt, %s ok\n' "${flagged}" "${exempt}" "${ok}"

  if [[ "${flagged}" -eq 0 ]]; then
    printf 'OK\n'
    exit 0
  fi

  exit 1
}

main "$@"
