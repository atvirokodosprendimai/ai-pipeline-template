#!/usr/bin/env bash
# Re-arm ONE bot PR by pushing an empty commit to its head branch, firing
# `pull_request: synchronize` so the absent required judge check finally runs.
#
# Usage: rearm.sh <repo-slug> <pr-number> <head-branch>     (e.g. owner/name)
# Auth:  GH_TOKEN env (a bot-push app token with contents:write on the repo).
# Emits exactly one structured result line for the orchestrator to parse:
#   OUTCOME=rearmed|skipped|error REASON=<slug>
#
# Safety invariants (mirror conflict-heal/rebase.sh):
#   - bot/* branches ONLY (R3) — a non-bot branch returns BEFORE any git call.
#   - an EMPTY commit + a NORMAL push (R2/KTD1) — it is a new commit, never a
#     history rewrite, so no --force is used or needed. A non-fast-forward push
#     (branch moved under us) surfaces as OUTCOME=error and is retried next tick.
# The runner is ephemeral and the clone is a temp dir removed on return, so
# there is no box-state risk.
set -euo pipefail

rearm_pr() {
  local repo="${1:-}" pr_number="${2:-}" branch="${3:-}"

  if [[ -z "$repo" || -z "$pr_number" || -z "$branch" ]]; then
    echo "OUTCOME=skipped REASON=missing-args"
    return 0
  fi

  # LOAD-BEARING GUARD (R3): never touch a non-bot branch. This MUST precede
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
  git -C "$workdir" checkout "$branch"

  # Identity for the empty commit (the box's bot identity).
  git -C "$workdir" config user.name "pupabobas[bot]"
  git -C "$workdir" config user.email "pupabobas[bot]@users.noreply.github.com"

  git -C "$workdir" commit --allow-empty \
    -m "chore: re-arm impl-judge (merge-lane heal)"

  if ! git -C "$workdir" push origin "$branch"; then
    echo "OUTCOME=error REASON=push-failed"
    return 0
  fi
  echo "OUTCOME=rearmed REASON=empty-commit-pushed"
  return 0
}

# Execute only when run directly; sourcing (tests) exposes rearm_pr without
# running it.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  rearm_pr "$@"
fi
