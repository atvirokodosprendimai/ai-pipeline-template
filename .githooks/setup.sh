#!/usr/bin/env bash
# One-shot setup: wire git to use .githooks/ for client-side policy hooks.
#
# Usage:
#   bash .githooks/setup.sh
#
# Invocation via `bash` is the documented form because some clones / file
# systems can strip the +x bit, in which case `.githooks/setup.sh` (without
# `bash`) would fail with "Permission denied". `bash <path>` always works.
# After this script runs, `chmod +x` is applied to the hook scripts so
# subsequent direct invocations also work.
#
# Idempotent. Run after fresh clone, or as part of any agent (Codex/Aider/etc)
# bootstrap. CI does NOT run this — workflow-level enforcement lives in
# .github/workflows/pii-policy-check.yml as the unbypassable required check.

set -euo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
  printf 'setup: not inside a git repo\n' >&2
  exit 1
}

cd "$repo_root"

# Wire core.hooksPath
git config core.hooksPath .githooks

# Ensure scripts are executable (clones may strip the +x bit on some FSes)
chmod +x .githooks/pre-commit .githooks/pre-push

printf 'githooks: configured\n'
printf '  core.hooksPath = .githooks\n'
printf '  enabled hooks:\n'
# Listing is non-fatal: under `set -euo pipefail`, a `grep` that finds
# no matches exits non-zero and would kill an already-successful setup.
# Trap that case with `|| true` so the configure step's success is never
# undone by a cosmetic listing failure.
{
  ls -1 .githooks/ \
    | grep -vE '^(setup\.sh|README\.md)$' \
    | sed 's/^/    /'
} || true
