#!/usr/bin/env bash
# Rebase ONE bot PR head branch onto origin/main in a throwaway clone.
#
# Usage: rebase.sh <repo-slug> <pr-number> <head-branch>     (e.g. owner/name)
# Auth:  GH_TOKEN env (a bot-push app token with contents:write on the repo).
# Emits exactly one structured result line for the orchestrator to parse:
#   OUTCOME=rebased|conflict|empty|skipped REASON=<slug>
#
# Force-push safety is the load-bearing invariant of this whole feature:
#   - bot/* branches ONLY (R4) — a non-bot branch returns BEFORE any git call.
#   - --force-with-lease ONLY, never bare --force (R4) — a concurrent push to
#     the branch is never clobbered.
#   - empty-after-rebase is NOT pushed (R6) — content already in main; flag it.
# The runner is ephemeral and the clone is a temp dir removed on return, so
# there is no box-state risk (KTD-2).
set -euo pipefail

rebase_pr() {
  local repo="${1:-}" pr_number="${2:-}" branch="${3:-}"

  if [[ -z "$repo" || -z "$pr_number" || -z "$branch" ]]; then
    echo "OUTCOME=skipped REASON=missing-args"
    return 0
  fi

  # LOAD-BEARING GUARD (R4): never touch a non-bot branch. This MUST precede
  # every git invocation so a human PR can never reach a clone/push line.
  case "$branch" in
    bot/*) ;;
    *)
      echo "OUTCOME=skipped REASON=non-bot-branch"
      return 0
      ;;
  esac

  local workdir
  workdir="$(mktemp -d)"
  # shellcheck disable=SC2064  # expand workdir now, on trap registration
  trap "rm -rf '$workdir'" RETURN

  git clone --quiet \
    "https://x-access-token:${GH_TOKEN:-}@github.com/${repo}.git" "$workdir"
  git -C "$workdir" fetch origin main --quiet
  git -C "$workdir" checkout "$branch"

  if ! git -C "$workdir" rebase origin/main; then
    git -C "$workdir" rebase --abort || true
    echo "OUTCOME=conflict REASON=rebase-conflict"
    return 0
  fi

  # R6: a PR whose content already merged rebases to an empty diff vs main.
  # Pushing an empty branch is meaningless — flag it instead.
  if git -C "$workdir" diff --quiet origin/main; then
    echo "OUTCOME=empty REASON=content-already-in-main"
    return 0
  fi

  git -C "$workdir" push --force-with-lease origin "$branch"
  echo "OUTCOME=rebased REASON=clean"
  return 0
}

# Execute only when run directly; sourcing (tests) exposes rebase_pr without
# running it.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  rebase_pr "$@"
fi
