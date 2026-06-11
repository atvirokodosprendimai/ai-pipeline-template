"""Resolution facts from git itself — the host-neutral source of truth.

A resolved issue is one whose resolution PR merged; after a squash merge the
commit subject carries the PR title (plus a trailing "(#N)"). Reading that
from the box's clone works identically on every git host and avoids the
GitHub Search API entirely (quoted-phrase search is token-loose; see the
2026-06-11 resolved-guard incident).

Git facts can lag the host (a PR merged seconds ago may not be fetched yet),
so a git MISS is not authoritative — callers fall back to the host lookup.
A git HIT is authoritative: the commit is reachable from the default branch.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Callable, Protocol

log = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 60


class GitFactsUnavailable(RuntimeError):
    pass


class _ResolutionHost(Protocol):
    def has_merged_resolution_pr(self, issue_number: int) -> bool: ...


def _resolution_pattern(issue_number: int) -> re.Pattern[str]:
    # Same exact-match discipline as GitHubClient.has_merged_resolution_pr:
    # leading impl|spec|fix prefix, then either the canonical "Issue #N" form
    # (no alphanumeric continuation) or the Copilot-era "(Issue #N)" suffix —
    # which after a squash merge is followed by the PR number "(#M)".
    return re.compile(
        rf"^(?:impl|spec|fix): (?:Issue #{issue_number}(?!\w)|.*\(Issue #{issue_number}\)( \(#\d+\))?\s*$)"
    )


def has_merged_resolution_commit(
    repo_path: Path | str, issue_number: int, *, branch: str = "origin/main"
) -> bool:
    repo = Path(repo_path)
    if not (repo / ".git").exists():
        raise GitFactsUnavailable(f"no git clone at {repo}")
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                branch,
                f"--grep=Issue #{issue_number}",
                "--fixed-strings",
                "--format=%s",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitFactsUnavailable(str(exc)) from exc
    if result.returncode != 0:
        raise GitFactsUnavailable(result.stderr.strip()[:200])
    pattern = _resolution_pattern(issue_number)
    return any(pattern.match(line) for line in result.stdout.splitlines())


def make_resolution_lookup(
    repo_path: Path | str, host: _ResolutionHost, *, branch: str = "origin/main"
) -> Callable[[int], bool]:
    """Git-first resolution lookup with host fallback.

    Git HIT -> resolved, no host call. Git MISS or unavailable -> defer to
    the host API (the clone may simply not have fetched the merge yet).
    """

    def lookup(issue_number: int) -> bool:
        try:
            if has_merged_resolution_commit(repo_path, issue_number, branch=branch):
                return True
        except GitFactsUnavailable as exc:
            log.warning("gitfacts unavailable for #%s (%s); using host lookup", issue_number, exc)
        return host.has_merged_resolution_pr(issue_number)

    return lookup
