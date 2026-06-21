#!/usr/bin/env bash
# Path-scoped pre-merge PII gate — shared implementation.
#
# Extracted verbatim from .github/workflows/pii-policy-check.yml so BOTH CI
# paths run the identical guard: the fork-side Actions workflow
# (.github/workflows/external-pr-ci.yml) AND the bot-side box CI invoke this
# one script. One source of truth = the two paths cannot drift, which is the
# load-bearing "no window without a leak guard" rule of the #1599 cutover.
#
# Scans every commit in BASE_SHA..HEAD_SHA for disallowed content under the
# policy-restricted paths docs/outreach/** and docs/customers/**. See the
# workflow header for the full threat model (the 2026-05-09 PR #820 stargazer
# email incident).
#
# Inputs (env):
#   BASE_SHA  base commit of the PR range (exclusive)
#   HEAD_SHA  head commit of the PR range (inclusive)
#
# Exit: 0 = PASS (no disallowed content), 1 = FAIL or unresolvable SHA.

set -euo pipefail

: "${BASE_SHA:?BASE_SHA env var is required}"
: "${HEAD_SHA:?HEAD_SHA env var is required}"

# Ensure the base commit is fetched locally (fetch-depth: 0 is
# usually enough, but explicit fetch is cheap and bulletproofs
# against shallow-clone edge cases).
git fetch --no-tags --quiet origin "$BASE_SHA" 2>/dev/null || true

if ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  echo "::error::could not resolve base SHA ${BASE_SHA}"
  exit 1
fi
if ! git cat-file -e "${HEAD_SHA}^{commit}" 2>/dev/null; then
  echo "::error::could not resolve head SHA ${HEAD_SHA}"
  exit 1
fi

# All commits in the PR range. We collect restricted-path files
# PER-COMMIT (via git diff-tree on each commit) rather than from
# the endpoint diff (BASE..HEAD), so files that existed in a
# restricted path in an intermediate commit but were renamed/moved
# OUT before HEAD are still scanned. The endpoint-diff approach
# would miss the commit-then-move-out bypass.
mapfile -t commits < <(git rev-list "${BASE_SHA}..${HEAD_SHA}")
if [ "${#commits[@]}" -eq 0 ]; then
  echo "No commits in range. PASS."
  exit 0
fi
echo "Inspecting ${#commits[@]} commit(s) in range ${BASE_SHA:0:7}..${HEAD_SHA:0:7}"
echo

# Encode workflow-command PROPERTY values per the actions/toolkit
# `escapeProperty` rules
# (https://github.com/actions/toolkit/blob/main/packages/core/src/command.ts):
# %->%25, CR->%0D, LF->%0A, AND the property separators :->%3A , ->%2C.
# `%` MUST be escaped first so the later replacements aren't re-encoded.
# Filenames come from user-controlled diffs, so a name containing `,`
# or `:` would otherwise break the annotation or inject extra
# `file=`/`line=` properties.
gh_escape() {
  local s="$1"
  s="${s//%/%25}"
  s="${s//$'\r'/%0D}"
  s="${s//$'\n'/%0A}"
  s="${s//:/%3A}"
  s="${s//,/%2C}"
  printf '%s' "$s"
}

# Email regex with allow-list for known-benign forms.
# example.com is RFC 2606 reserved.
# noreply.github.com is GitHub system mail.
# users.noreply.github.com is the per-user GitHub privacy domain.
# Patterns via ENVIRON to avoid awk -v backslash-stripping.
export EMAIL_PATTERN='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
export ALLOW_PATTERN='^@(example\.com|noreply\.github\.com|users\.noreply\.github\.com)$'

fail=0
any_restricted_seen=0

for commit in "${commits[@]}"; do
  # Files this specific commit added/modified/renamed/copied/type-changed
  # under a restricted path. Captures BOTH renames-into and renames-out-of
  # by emitting both source + dest paths via -M / --name-only.
  #
  # -m makes diff-tree emit the diff of a MERGE commit against each
  # parent; without it a clean merge yields NO paths, so PII pulled in
  # (or resolved during conflict resolution) at a merge commit would be
  # invisible. -m can list a path once per parent, so dedupe with sort -u.
  mapfile -t commit_files < <(
    git diff-tree --no-commit-id --name-only -r -M -m --diff-filter=ACMRT "$commit" \
      | grep -E '^docs/(outreach|customers)/' \
      | sort -u \
      || true
  )

  [ "${#commit_files[@]}" -eq 0 ] && continue
  any_restricted_seen=1

  for f in "${commit_files[@]}"; do

    # 1. Hard block: ANY content under docs/customers/ at ANY commit.
    # If the commit ADDED a file under that prefix, fail — even if a
    # later commit deleted it.
    if [[ "$f" =~ ^docs/customers/ ]]; then
      if git cat-file -e "${commit}:${f}" 2>/dev/null; then
        ef="$(gh_escape "$f")"
        echo "::error file=${ef}::commit ${commit:0:7} contains a file under docs/customers/** — that subtree is a policy-banned namespace (this workflow's rule, on top of company/system-prompt.md customer-PII ban). Customer/sponsor exchanges go to private operator notes."
        fail=1
      fi
      continue
    fi

    # 2. Email scan against the file content AT THIS COMMIT. Skip
    # silently if the file didn't exist at this commit.
    content=$(git cat-file -p "${commit}:${f}" 2>/dev/null) || continue
    [ -z "$content" ] && continue

    hits=$(printf '%s\n' "$content" \
      | awk 'BEGIN { pat = ENVIRON["EMAIL_PATTERN"] }
             {
               line = $0
               while (match(line, pat)) {
                 m = substr(line, RSTART, RLENGTH)
                 printf "%d:%s\n", NR, m
                 line = substr(line, RSTART + RLENGTH)
               }
             }' \
      | awk -F: 'BEGIN { allow = ENVIRON["ALLOW_PATTERN"] }
                 {
                   email = $2
                   pos = index(email, "@")
                   domain = substr(email, pos)
                   if (domain !~ allow) print
                 }' \
      || true)

    if [ -n "$hits" ]; then
      fail=1
      ef="$(gh_escape "$f")"
      # IMPORTANT: never echo the matched email VALUE. Actions logs
      # on a public repo are public; printing the address would
      # re-expose the very PII this gate exists to keep off public
      # surfaces. Report line numbers + a count only.
      while IFS= read -r line; do
        lineno=$(printf '%s' "$line" | cut -d: -f1)
        # lineno is digits from cut output; no need to escape
        echo "::error file=${ef},line=${lineno}::commit ${commit:0:7} contains an email address in this path. This workflow's stricter rule (on top of company/system-prompt.md customer-PII ban) forbids ANY email here, since the path historically accumulated third-party recipient PII."
      done <<< "$hits"
      hit_count=$(printf '%s\n' "$hits" | grep -c . || true)
      hit_lines=$(printf '%s\n' "$hits" | cut -d: -f1 | paste -sd, -)
      echo "    commit ${commit:0:7}: ${hit_count} disallowed email(s) in $f at line(s): ${hit_lines}"
    fi
  done
done

if [ "$fail" -ne 0 ]; then
  echo
  echo "PII policy check FAILED. Redact and re-push (history will need to be rewritten if PII was committed-then-removed within the range — squash or interactive-rebase before push), OR move the offending content to a private operator system."
  exit 1
fi

if [ "$any_restricted_seen" -eq 0 ]; then
  echo "No policy-restricted paths touched in any commit in range. PASS."
else
  echo "PII policy check PASSED across all commits in range."
fi
