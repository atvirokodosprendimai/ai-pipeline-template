#!/usr/bin/env bash
# Characterization tests for check-pii-policy.sh — the extracted PII guard.
# Builds throwaway git repos and asserts the documented behavior of the
# inline pii-policy-check.yml scan that this script replaced. Drift here
# means a real public-repo email-leak vector, so these are the parity proof.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINTER="${SCRIPT_DIR}/check-pii-policy.sh"

tmpdir="$(mktemp -d)"
cleanup() { rm -rf "${tmpdir}"; }
trap cleanup EXIT

pass_count=0
total_count=7

# Build the disallowed email at runtime so the literal address never sits in
# this file (belt-and-suspenders; the gate only scans docs/ paths anyway).
LEAK_LOCAL='leaker'
LEAK_DOMAIN='evil-corp.test'
LEAK_EMAIL="${LEAK_LOCAL}@${LEAK_DOMAIN}"

record_pass() { pass_count=$((pass_count + 1)); printf '[PASS] %s\n' "$1"; }
record_fail() { printf '[FAIL] %s\n%s\n' "$1" "$2"; }

# Init a repo, return its path. Caller adds commits via gc().
new_repo() {
  local name="$1"
  local root="${tmpdir}/${name}"
  mkdir -p "${root}"
  git -C "${root}" init -q
  git -C "${root}" config user.email "test@example.com"
  git -C "${root}" config user.name "test"
  git -C "${root}" config commit.gpgsign false
  printf '%s\n' "${root}"
}

# Stage everything and commit; echo the new commit SHA.
gc() {
  local root="$1" msg="$2"
  git -C "${root}" add -A
  git -C "${root}" commit -q -m "${msg}" --allow-empty
  git -C "${root}" rev-parse HEAD
}

# Run the linter against a repo with given BASE/HEAD; capture output+status.
run_guard() {
  local root="$1" base="$2" head="$3" out="$4" stat="$5"
  local status=0
  ( cd "${root}" && BASE_SHA="${base}" HEAD_SHA="${head}" bash "${LINTER}" ) \
    > "${out}" 2>&1 || status=$?
  printf '%s\n' "${status}" > "${stat}"
}

# ---------------------------------------------------------------------------
# (a) Clean diff under a restricted path → exit 0, PASS.
# ---------------------------------------------------------------------------
r="$(new_repo clean)"
base="$(gc "${r}" "base")"
mkdir -p "${r}/docs/outreach"
printf 'Stargazer A — handle redacted, no email here.\n' > "${r}/docs/outreach/notes.md"
head="$(gc "${r}" "clean outreach note")"
run_guard "${r}" "${base}" "${head}" "${tmpdir}/a.out" "${tmpdir}/a.stat"
if [ "$(cat "${tmpdir}/a.stat")" = "0" ] && grep -q "PASSED" "${tmpdir}/a.out"; then
  record_pass "clean diff -> exit 0 PASS"
else
  record_fail "clean diff -> exit 0 PASS" "status=$(cat "${tmpdir}/a.stat") out:$(cat "${tmpdir}/a.out")"
fi

# ---------------------------------------------------------------------------
# (b) Planted disallowed email at HEAD → non-zero, annotation, value redacted.
# ---------------------------------------------------------------------------
r="$(new_repo planted)"
base="$(gc "${r}" "base")"
mkdir -p "${r}/docs/outreach"
printf 'Contact: %s\n' "${LEAK_EMAIL}" > "${r}/docs/outreach/leak.md"
head="$(gc "${r}" "add email")"
run_guard "${r}" "${base}" "${head}" "${tmpdir}/b.out" "${tmpdir}/b.stat"
if [ "$(cat "${tmpdir}/b.stat")" != "0" ] \
   && grep -q "::error file=docs/outreach/leak.md,line=" "${tmpdir}/b.out" \
   && ! grep -qF "${LEAK_EMAIL}" "${tmpdir}/b.out"; then
  record_pass "planted email at HEAD -> fail, annotation, value not leaked"
else
  record_fail "planted email at HEAD -> fail, annotation, value not leaked" \
    "status=$(cat "${tmpdir}/b.stat") out:$(cat "${tmpdir}/b.out")"
fi

# ---------------------------------------------------------------------------
# (c) Email in an intermediate commit then moved OUT before HEAD → still caught.
# ---------------------------------------------------------------------------
r="$(new_repo moveout)"
base="$(gc "${r}" "base")"
mkdir -p "${r}/docs/outreach"
printf 'Contact: %s\n' "${LEAK_EMAIL}" > "${r}/docs/outreach/temp.md"
gc "${r}" "intermediate: add email under outreach" > /dev/null
# Move the file OUT of the restricted path before HEAD.
mkdir -p "${r}/docs/elsewhere"
git -C "${r}" mv docs/outreach/temp.md docs/elsewhere/temp.md
head="$(gc "${r}" "move email out of outreach")"
run_guard "${r}" "${base}" "${head}" "${tmpdir}/c.out" "${tmpdir}/c.stat"
if [ "$(cat "${tmpdir}/c.stat")" != "0" ] && grep -q "::error" "${tmpdir}/c.out"; then
  record_pass "commit-then-move-out -> still caught"
else
  record_fail "commit-then-move-out -> still caught" \
    "status=$(cat "${tmpdir}/c.stat") out:$(cat "${tmpdir}/c.out")"
fi

# ---------------------------------------------------------------------------
# (d) Filename containing ',' → annotation property escaped (%2C), not injected.
# ---------------------------------------------------------------------------
r="$(new_repo comma)"
base="$(gc "${r}" "base")"
mkdir -p "${r}/docs/outreach"
printf 'Contact: %s\n' "${LEAK_EMAIL}" > "${r}/docs/outreach/a,b.md"
head="$(gc "${r}" "add comma-named file with email")"
run_guard "${r}" "${base}" "${head}" "${tmpdir}/d.out" "${tmpdir}/d.stat"
if [ "$(cat "${tmpdir}/d.stat")" != "0" ] \
   && grep -q "file=docs/outreach/a%2Cb.md," "${tmpdir}/d.out"; then
  record_pass "comma in filename -> escaped to %2C"
else
  record_fail "comma in filename -> escaped to %2C" \
    "status=$(cat "${tmpdir}/d.stat") out:$(cat "${tmpdir}/d.out")"
fi

# ---------------------------------------------------------------------------
# (e) Unresolvable BASE_SHA → error exit, not a false PASS.
# ---------------------------------------------------------------------------
r="$(new_repo badbase)"
head="$(gc "${r}" "only commit")"
run_guard "${r}" "0000000000000000000000000000000000000000" "${head}" "${tmpdir}/e.out" "${tmpdir}/e.stat"
if [ "$(cat "${tmpdir}/e.stat")" != "0" ] \
   && grep -q "could not resolve base SHA" "${tmpdir}/e.out" \
   && ! grep -q "PASS" "${tmpdir}/e.out"; then
  record_pass "unresolvable base SHA -> error, not PASS"
else
  record_fail "unresolvable base SHA -> error, not PASS" \
    "status=$(cat "${tmpdir}/e.stat") out:$(cat "${tmpdir}/e.out")"
fi

# ---------------------------------------------------------------------------
# (f) Any file under docs/customers/ → hard block fail.
# ---------------------------------------------------------------------------
r="$(new_repo customers)"
base="$(gc "${r}" "base")"
mkdir -p "${r}/docs/customers"
printf 'no email, just a banned namespace file\n' > "${r}/docs/customers/acme.md"
head="$(gc "${r}" "add customers file")"
run_guard "${r}" "${base}" "${head}" "${tmpdir}/f.out" "${tmpdir}/f.stat"
if [ "$(cat "${tmpdir}/f.stat")" != "0" ] \
   && grep -q "policy-banned namespace" "${tmpdir}/f.out"; then
  record_pass "docs/customers/ file -> hard block fail"
else
  record_fail "docs/customers/ file -> hard block fail" \
    "status=$(cat "${tmpdir}/f.stat") out:$(cat "${tmpdir}/f.out")"
fi

# ---------------------------------------------------------------------------
# (g) Allow-listed domain (example.com) → PASS.
# ---------------------------------------------------------------------------
r="$(new_repo allowlist)"
base="$(gc "${r}" "base")"
mkdir -p "${r}/docs/outreach"
printf 'Reach the bot at noreply@example.com — RFC-reserved, allowed.\n' \
  > "${r}/docs/outreach/ok.md"
head="$(gc "${r}" "add allow-listed email")"
run_guard "${r}" "${base}" "${head}" "${tmpdir}/g.out" "${tmpdir}/g.stat"
if [ "$(cat "${tmpdir}/g.stat")" = "0" ] && grep -q "PASSED" "${tmpdir}/g.out"; then
  record_pass "allow-listed domain -> PASS"
else
  record_fail "allow-listed domain -> PASS" \
    "status=$(cat "${tmpdir}/g.stat") out:$(cat "${tmpdir}/g.out")"
fi

# ---------------------------------------------------------------------------
printf '\nSummary: %s/%s passed\n' "${pass_count}" "${total_count}"
[ "${pass_count}" -eq "${total_count}" ]
