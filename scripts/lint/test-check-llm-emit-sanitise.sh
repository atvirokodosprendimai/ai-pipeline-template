#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINTER="${SCRIPT_DIR}/check-llm-emit-sanitise.sh"

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "${tmpdir}"
}
trap cleanup EXIT

pass_count=0
total_count=5
openrouter_signal='Open''Router'
assessment_file='assessment.''json'
issue_create_sink='gh issue'' create'
pr_comment_sink='gh pr'' comment'
git_commit_sink='git ''commit'
exempt_marker='# sanitise-wall:'' exempt test-only'

make_tree() {
  local name="$1"
  local root="${tmpdir}/${name}"

  mkdir -p "${root}/.github/workflows" "${root}/company/scripts" "${root}/scripts"
  printf '#!/usr/bin/env bash\nset -euo pipefail\ncat >/dev/null\n' > "${root}/company/scripts/sanitise.sh"
  printf '%s\n' "${root}"
}

record_pass() {
  local name="$1"

  pass_count=$((pass_count + 1))
  printf '[PASS] %s\n' "${name}"
}

record_fail() {
  local name="$1"
  local details="$2"

  printf '[FAIL] %s\n%s\n' "${name}" "${details}"
}

run_linter() {
  local root="$1"
  local output_file="$2"
  local status_file="$3"
  local status=0

  bash "${LINTER}" "${root}" > "${output_file}" 2>&1 || status=$?
  printf '%s\n' "${status}" > "${status_file}"
}

assert_contains() {
  local file="$1"
  local needle="$2"

  grep -Fq "${needle}" "${file}"
}

test_flags_unsanitised_llm_sink() {
  local name='flags unsanitised LLM sink'
  local root output status_file status

  root="$(make_tree flag)"
  output="${tmpdir}/flag.out"
  status_file="${tmpdir}/flag.status"

  cat > "${root}/.github/workflows/fake.yml" <<YAML
name: fake
on: workflow_dispatch
jobs:
  fake:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${openrouter_signal} generated text" > ${assessment_file}
          ${issue_create_sink} --title "LLM output" --body-file ${assessment_file}
YAML

  run_linter "${root}" "${output}" "${status_file}"
  status="$(cat "${status_file}")"

  if [[ "${status}" -ne 0 ]] && assert_contains "${output}" '[FLAGGED] .github/workflows/fake.yml'; then
    record_pass "${name}"
  else
    record_fail "${name}" "$(cat "${output}")"
  fi
}

test_passes_sanitised_llm_sink() {
  local name='passes sanitised LLM sink'
  local root output status_file status

  root="$(make_tree ok)"
  output="${tmpdir}/ok.out"
  status_file="${tmpdir}/ok.status"

  cat > "${root}/.github/workflows/fake.yml" <<YAML
name: fake
on: workflow_dispatch
jobs:
  fake:
    runs-on: ubuntu-latest
    steps:
      - run: |
          body="${openrouter_signal} generated text"
          if ! printf '%s' "\$body" | bash company/scripts/sanitise.sh; then
            exit 1
          fi
          ${pr_comment_sink} 123 --body "\$body"
YAML

  run_linter "${root}" "${output}" "${status_file}"
  status="$(cat "${status_file}")"

  if [[ "${status}" -eq 0 ]] && assert_contains "${output}" '[OK]      .github/workflows/fake.yml'; then
    record_pass "${name}"
  else
    record_fail "${name}" "$(cat "${output}")"
  fi
}

test_ignores_non_llm_sink() {
  local name='ignores non-LLM sink'
  local root output status_file status

  root="$(make_tree nonllm)"
  output="${tmpdir}/nonllm.out"
  status_file="${tmpdir}/nonllm.status"

  cat > "${root}/.github/workflows/fake.yml" <<YAML
name: fake
on: workflow_dispatch
jobs:
  fake:
    runs-on: ubuntu-latest
    steps:
      - run: ${pr_comment_sink} 123 --body "static update"
YAML

  run_linter "${root}" "${output}" "${status_file}"
  status="$(cat "${status_file}")"

  if [[ "${status}" -eq 0 ]] && ! assert_contains "${output}" '[FLAGGED]'; then
    record_pass "${name}"
  else
    record_fail "${name}" "$(cat "${output}")"
  fi
}

test_exempts_marked_llm_sink() {
  local name='exempts marked LLM sink'
  local root output status_file status

  root="$(make_tree exempt)"
  output="${tmpdir}/exempt.out"
  status_file="${tmpdir}/exempt.status"

  cat > "${root}/.github/workflows/fake.yml" <<YAML
name: fake
${exempt_marker}
on: workflow_dispatch
jobs:
  fake:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${openrouter_signal} generated text" > ${assessment_file}
          ${git_commit_sink} -am "generated"
YAML

  run_linter "${root}" "${output}" "${status_file}"
  status="$(cat "${status_file}")"

  if [[ "${status}" -eq 0 ]] && assert_contains "${output}" '[EXEMPT]  .github/workflows/fake.yml — reason: test-only'; then
    record_pass "${name}"
  else
    record_fail "${name}" "$(cat "${output}")"
  fi
}

test_flags_comment_only_sanitise_mention() {
  local name='flags comment-only sanitise mention'
  local root output status_file status

  root="$(make_tree comment)"
  output="${tmpdir}/comment.out"
  status_file="${tmpdir}/comment.status"

  cat > "${root}/.github/workflows/fake.yml" <<YAML
name: fake
on: workflow_dispatch
jobs:
  fake:
    runs-on: ubuntu-latest
    steps:
      - run: |
          # This should call company/scripts/sanitise.sh before publishing.
          echo "${openrouter_signal} generated text" > ${assessment_file}
          ${issue_create_sink} --title "LLM output" --body-file ${assessment_file}
YAML

  run_linter "${root}" "${output}" "${status_file}"
  status="$(cat "${status_file}")"

  if [[ "${status}" -ne 0 ]] && assert_contains "${output}" '[FLAGGED] .github/workflows/fake.yml'; then
    record_pass "${name}"
  else
    record_fail "${name}" "$(cat "${output}")"
  fi
}

test_flags_unsanitised_llm_sink
test_passes_sanitised_llm_sink
test_ignores_non_llm_sink
test_exempts_marked_llm_sink
test_flags_comment_only_sanitise_mention

if [[ "${pass_count}" -eq "${total_count}" ]]; then
  printf 'PASS %s/%s\n' "${pass_count}" "${total_count}"
  exit 0
fi

printf 'FAIL %s/%s\n' "${pass_count}" "${total_count}"
exit 1
