"""Box-side pre-merge CI for bot-authored PRs (cutover #1599 U9).

The box is the CI for its own PRs: before the merge gate it runs the
verification suite, `company/scripts/sanitise.sh` over the PR diff, and the
path-scoped PII rules that `pii-policy-check.yml` enforces (docs/outreach/**
email ban + docs/customers/** banned namespace — born from the 2026-05-09
PR #820 stargazer-email incident). The resulting verdict feeds
`merge_gate.ensure_mergeable` instead of an Actions check-runs poll; Actions
CI remains only for external PRs (U10's retained sandbox lane).

Fail closed everywhere: a stage that cannot run is a failure, never a pass.
PII failure messages report path + line number only — never the matched
address — because gate reasons land on public surfaces.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from wgmesh_pipeline.verification import run_verification

log = logging.getLogger(__name__)

SANITISE_SCRIPT = Path(__file__).resolve().parents[3] / "company" / "scripts" / "sanitise.sh"
SANITISE_TIMEOUT_SECONDS = 120
GIT_TIMEOUT_SECONDS = 120

# Mirrors pii-policy-check.yml: scan only policy-restricted paths.
RESTRICTED_PATH_RE = re.compile(r"^docs/(outreach|customers)/")
CUSTOMERS_PREFIX = "docs/customers/"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# example.com is RFC 2606 reserved; the github.com domains are GH system mail.
ALLOWED_EMAIL_DOMAIN_RE = re.compile(
    r"^@(example\.com|noreply\.github\.com|users\.noreply\.github\.com)$"
)


class _CiSurface(Protocol):
    def get_pr(self, number: int) -> dict[str, Any]: ...

    def get_diff(self, pr_number: int) -> str: ...


@dataclass(frozen=True)
class BoxCiResult:
    green: bool
    failures: tuple[str, ...]


def run_box_ci(
    client: _CiSurface,
    pr_number: int,
    *,
    repo_path: Path,
    verifier: Callable[..., dict] = run_verification,
    sanitiser: Callable[[str], bool] | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> BoxCiResult:
    """Run the full box-side CI for one PR and return a single verdict.

    Stages run independently and failures accumulate, so an escalation
    carries every reason at once instead of one per retry.
    """
    sanitise = sanitiser if sanitiser is not None else _run_sanitise
    failures: list[str] = []

    # Fail closed on the very first read too: a forge outage is a red
    # verdict, never an exception stranding the gate mid-merge.
    try:
        pr = client.get_pr(pr_number)
    except Exception:
        log.exception("box ci: could not fetch PR #%s", pr_number)
        return BoxCiResult(
            green=False,
            failures=(f"box ci: could not fetch PR #{pr_number} (see box logs)",),
        )
    branch = str(((pr.get("head") or {}).get("ref")) or "")
    head_sha = str(((pr.get("head") or {}).get("sha")) or "")
    base_sha = str(((pr.get("base") or {}).get("sha")) or "")
    if not branch or not head_sha or not base_sha:
        return BoxCiResult(
            green=False,
            failures=(f"box ci: PR #{pr_number} is missing head/base refs — cannot verify",),
        )

    # Fail closed, loudly: a stage that cannot run (missing clone, dead git)
    # is a red verdict with the cause in the reasons — never an exception
    # that strands the issue mid-merge, never a silent pass.
    try:
        verification = verifier(repo_path, branch)
    except Exception as exc:
        log.exception("box ci: verification could not run for PR #%s: %s", pr_number, exc)
        verification = {"tests_passed": False, "reason": "verification could not run (see box logs)"}
    if not verification.get("tests_passed", False):
        reason = verification.get("reason") or verification.get("failed_step") or "tests failed"
        failures.append(f"box ci: verification failed ({reason})")

    try:
        diff = client.get_diff(pr_number)
    except Exception as exc:
        log.exception("box ci: could not fetch diff for PR #%s: %s", pr_number, exc)
        failures.append("box ci: could not fetch PR diff (see box logs)")
    else:
        if not sanitise(diff):
            failures.append("box ci: sanitise failed")

    try:
        pii = pii_path_violations(repo_path, base_sha, head_sha, runner=runner)
    except Exception as exc:
        log.exception("box ci: pii check could not run for PR #%s: %s", pr_number, exc)
        pii = ("pii check could not run (see box logs)",)
    failures.extend(f"box ci: pii violation: {violation}" for violation in pii)

    if failures:
        log.warning("box ci: PR #%s RED: %s", pr_number, "; ".join(failures))
    else:
        log.info("box ci: PR #%s green (verification + sanitise + pii)", pr_number)
    return BoxCiResult(green=not failures, failures=tuple(failures))


def make_box_ci_runner(
    repo_path: str | Path, **overrides: Any
) -> Callable[[Any, int], BoxCiResult]:
    """Bind a repo clone path (and optional stage overrides, for tests) into
    the `(client, pr_number) -> BoxCiResult` shape the gate consumes."""
    path = Path(repo_path)

    def _run(client: Any, pr_number: int) -> BoxCiResult:
        return run_box_ci(client, pr_number, repo_path=path, **overrides)

    return _run


def pii_path_violations(
    repo_path: Path,
    base_sha: str,
    head_sha: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> tuple[str, ...]:
    """Port of pii-policy-check.yml's scan, per-commit over base..head.

    Per-commit (not endpoint-diff) so content that lived under a restricted
    path in an intermediate commit but was renamed out before HEAD is still
    scanned — the commit-then-move-out bypass.
    """
    # Best-effort: make sure the base commit is reachable locally (the
    # verification stage already fetched the head branch).
    _git(runner, repo_path, "fetch", "--no-tags", "origin", base_sha)

    listed = _git(runner, repo_path, "rev-list", f"{base_sha}..{head_sha}")
    if listed.returncode != 0:
        return (f"pii check could not enumerate commits {base_sha[:7]}..{head_sha[:7]}: "
                f"{(listed.stderr or '').strip()}",)

    violations: list[str] = []
    for commit in [line for line in (listed.stdout or "").splitlines() if line.strip()]:
        tree = _git(
            runner,
            repo_path,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-M",
            "-m",
            "--diff-filter=ACMRT",
            commit,
        )
        if tree.returncode != 0:
            violations.append(
                f"pii check could not inspect commit {commit[:7]}: {(tree.stderr or '').strip()}"
            )
            continue
        files = sorted(
            {line for line in (tree.stdout or "").splitlines() if RESTRICTED_PATH_RE.match(line)}
        )
        for path in files:
            violations.extend(_scan_restricted_file(runner, repo_path, commit, path))
    return tuple(violations)


def _scan_restricted_file(
    runner: Callable[..., Any], repo_path: Path, commit: str, path: str
) -> list[str]:
    if path.startswith(CUSTOMERS_PREFIX):
        exists = _git(runner, repo_path, "cat-file", "-e", f"{commit}:{path}")
        if exists.returncode == 0:
            return [
                f"{path} (commit {commit[:7]}): docs/customers/** is a policy-banned "
                "namespace — customer/sponsor exchanges live in private operator notes"
            ]
        return []

    shown = _git(runner, repo_path, "cat-file", "-p", f"{commit}:{path}")
    if shown.returncode != 0:
        # File absent at this commit (renamed-out source path) — nothing to scan.
        return []
    found: list[str] = []
    for lineno, line in enumerate((shown.stdout or "").splitlines(), start=1):
        for match in EMAIL_RE.finditer(line):
            domain = match.group(0)[match.group(0).index("@"):]
            if not ALLOWED_EMAIL_DOMAIN_RE.match(domain):
                # Report position only — never the address itself.
                found.append(
                    f"{path}: disallowed email at line {lineno} (commit {commit[:7]})"
                )
    return found


def _git(runner: Callable[..., Any], repo_path: Path, *args: str) -> Any:
    return runner(
        ["git", *args],
        cwd=repo_path,
        check=False,
        text=True,
        capture_output=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def _run_sanitise(text: str) -> bool:
    try:
        completed = subprocess.run(
            [str(SANITISE_SCRIPT)],
            input=text,
            text=True,
            capture_output=True,
            check=False,
            timeout=SANITISE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0
