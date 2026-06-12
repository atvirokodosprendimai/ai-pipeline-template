"""Box-side pre-merge CI for bot PRs (cutover U9).

The box runs the verification suite + sanitise + the path-scoped PII rules
itself instead of waiting on Actions check-runs. All subprocess work is
stubbed at the subprocess boundary (fake `runner`); the composition logic —
verdict, fail-closed behavior, message hygiene — stays in the tested path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wgmesh_pipeline.forge.box_ci import (
    BoxCiResult,
    make_box_ci_runner,
    pii_path_violations,
    run_box_ci,
)


class FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeGit:
    """Subprocess-shaped stub: maps git argv tuples to canned results."""

    def __init__(self, responses: dict[tuple[str, ...], FakeCompleted]):
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> FakeCompleted:
        key = tuple(cmd)
        self.calls.append(key)
        if key in self.responses:
            return self.responses[key]
        # Unmapped fetches are benign (best-effort); anything else fails.
        if cmd[:2] == ["git", "fetch"]:
            return FakeCompleted(0)
        return FakeCompleted(returncode=128, stderr=f"unmapped: {cmd}")


REPO = Path("/repo")
BASE = "base000"
HEAD = "head999"


def _rev_list(*commits: str) -> dict[tuple[str, ...], FakeCompleted]:
    return {
        ("git", "rev-list", f"{BASE}..{HEAD}"): FakeCompleted(0, stdout="\n".join(commits) + ("\n" if commits else "")),
    }


def _diff_tree(commit: str, *files: str) -> dict[tuple[str, ...], FakeCompleted]:
    return {
        (
            "git",
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-M",
            "-m",
            "--diff-filter=ACMRT",
            commit,
        ): FakeCompleted(0, stdout="\n".join(files) + ("\n" if files else ""))
    }


def test_pii_clean_range_has_no_violations() -> None:
    git = FakeGit({**_rev_list("c1"), **_diff_tree("c1", "pipeline/x.py", "docs/plans/a.md")})

    violations = pii_path_violations(REPO, BASE, HEAD, runner=git)

    assert violations == ()


def test_pii_empty_commit_range_passes() -> None:
    git = FakeGit(_rev_list())

    assert pii_path_violations(REPO, BASE, HEAD, runner=git) == ()


def test_pii_customers_namespace_is_banned() -> None:
    git = FakeGit(
        {
            **_rev_list("c1"),
            **_diff_tree("c1", "docs/customers/acme.md"),
            ("git", "cat-file", "-e", "c1:docs/customers/acme.md"): FakeCompleted(0),
        }
    )

    violations = pii_path_violations(REPO, BASE, HEAD, runner=git)

    assert len(violations) == 1
    assert "docs/customers/" in violations[0]


def test_pii_email_in_outreach_is_blocked_and_value_never_leaks() -> None:
    content = "Dear stargazer,\ncontact: real.person@gmail.com\nthanks"
    git = FakeGit(
        {
            **_rev_list("c1"),
            **_diff_tree("c1", "docs/outreach/campaign.md"),
            ("git", "cat-file", "-p", "c1:docs/outreach/campaign.md"): FakeCompleted(0, stdout=content),
        }
    )

    violations = pii_path_violations(REPO, BASE, HEAD, runner=git)

    assert len(violations) == 1
    assert "docs/outreach/campaign.md" in violations[0]
    assert "line 2" in violations[0]
    # Never echo the matched address: the failure text lands in public
    # surfaces (PR comments, logs).
    assert "real.person@gmail.com" not in violations[0]
    assert "gmail" not in violations[0]


def test_pii_allow_listed_domains_pass() -> None:
    content = "a@example.com b@noreply.github.com c@users.noreply.github.com"
    git = FakeGit(
        {
            **_rev_list("c1"),
            **_diff_tree("c1", "docs/outreach/campaign.md"),
            ("git", "cat-file", "-p", "c1:docs/outreach/campaign.md"): FakeCompleted(0, stdout=content),
        }
    )

    assert pii_path_violations(REPO, BASE, HEAD, runner=git) == ()


def test_pii_scans_intermediate_commit_even_if_moved_out_before_head() -> None:
    """The commit-then-move-out bypass: PII added in c1 under a restricted
    path then renamed out in c2 must still be caught (per-commit scan)."""
    git = FakeGit(
        {
            **_rev_list("c2", "c1"),
            **_diff_tree("c1", "docs/outreach/leak.md"),
            **_diff_tree("c2", "docs/notes/leak.md"),
            ("git", "cat-file", "-p", "c1:docs/outreach/leak.md"): FakeCompleted(
                0, stdout="hidden@victim.org"
            ),
        }
    )

    violations = pii_path_violations(REPO, BASE, HEAD, runner=git)

    assert len(violations) == 1
    assert "docs/outreach/leak.md" in violations[0]


def test_pii_fails_closed_when_git_cannot_enumerate_commits() -> None:
    git = FakeGit({("git", "rev-list", f"{BASE}..{HEAD}"): FakeCompleted(128, stderr="bad revision")})

    violations = pii_path_violations(REPO, BASE, HEAD, runner=git)

    assert violations
    assert "could not" in violations[0]


def test_pii_fails_closed_when_diff_tree_fails() -> None:
    git = FakeGit({**_rev_list("c1")})  # diff-tree for c1 unmapped -> rc 128

    violations = pii_path_violations(REPO, BASE, HEAD, runner=git)

    assert violations
    assert "could not" in violations[0]


# ---- run_box_ci composition ----


class FakeForge:
    def __init__(self, *, pr: dict | None = None, diff: str = "+ok\n"):
        self.pr = pr if pr is not None else {
            "number": 7,
            "head": {"ref": "bot/impl-7", "sha": HEAD},
            "base": {"sha": BASE},
        }
        self.diff = diff
        self.diff_calls = 0

    def get_pr(self, number: int) -> dict:
        return self.pr

    def get_diff(self, pr_number: int) -> str:
        self.diff_calls += 1
        return self.diff


def _green_verifier(repo_path: Path, branch: str) -> dict:
    return {"tests_passed": True, "steps": [], "failed_step": None, "output_tail": ""}


def _red_verifier(repo_path: Path, branch: str) -> dict:
    return {
        "tests_passed": False,
        "steps": [],
        "failed_step": "go test",
        "output_tail": "FAIL",
        "reason": "go test failed",
    }


def _clean_git() -> FakeGit:
    return FakeGit(_rev_list())


def test_box_ci_green_when_all_stages_pass() -> None:
    result = run_box_ci(
        FakeForge(),
        7,
        repo_path=REPO,
        verifier=_green_verifier,
        sanitiser=lambda text: True,
        runner=_clean_git(),
    )

    assert result == BoxCiResult(green=True, failures=())


def test_box_ci_red_when_verification_fails() -> None:
    result = run_box_ci(
        FakeForge(),
        7,
        repo_path=REPO,
        verifier=_red_verifier,
        sanitiser=lambda text: True,
        runner=_clean_git(),
    )

    assert result.green is False
    assert any("go test failed" in f for f in result.failures)


def test_box_ci_red_when_sanitise_fails() -> None:
    result = run_box_ci(
        FakeForge(),
        7,
        repo_path=REPO,
        verifier=_green_verifier,
        sanitiser=lambda text: False,
        runner=_clean_git(),
    )

    assert result.green is False
    assert any("sanitise" in f for f in result.failures)


def test_box_ci_red_when_pii_violation_found() -> None:
    git = FakeGit(
        {
            **_rev_list("c1"),
            **_diff_tree("c1", "docs/customers/x.md"),
            ("git", "cat-file", "-e", "c1:docs/customers/x.md"): FakeCompleted(0),
        }
    )

    result = run_box_ci(
        FakeForge(),
        7,
        repo_path=REPO,
        verifier=_green_verifier,
        sanitiser=lambda text: True,
        runner=git,
    )

    assert result.green is False
    assert any("pii" in f for f in result.failures)


def test_box_ci_fails_closed_when_pr_shape_is_missing_refs() -> None:
    forge = FakeForge(pr={"number": 7})

    result = run_box_ci(
        forge,
        7,
        repo_path=REPO,
        verifier=_green_verifier,
        sanitiser=lambda text: True,
        runner=_clean_git(),
    )

    assert result.green is False


def test_box_ci_fails_closed_when_diff_fetch_raises() -> None:
    class BrokenDiff(FakeForge):
        def get_diff(self, pr_number: int) -> str:
            raise RuntimeError("503 from forge")

    result = run_box_ci(
        BrokenDiff(),
        7,
        repo_path=REPO,
        verifier=_green_verifier,
        sanitiser=lambda text: True,
        runner=_clean_git(),
    )

    assert result.green is False
    assert any("diff" in f for f in result.failures)


def test_box_ci_fails_closed_when_verifier_raises() -> None:
    """A missing clone / dead git must become a red verdict with the cause
    in the failures — never an exception that strands the issue mid-merge."""

    def broken_verifier(repo_path: Path, branch: str) -> dict:
        raise FileNotFoundError("/opt/wgmesh-checkout")

    result = run_box_ci(
        FakeForge(),
        7,
        repo_path=REPO,
        verifier=broken_verifier,
        sanitiser=lambda text: True,
        runner=_clean_git(),
    )

    assert result.green is False
    assert any("could not run" in f for f in result.failures)


def test_box_ci_accumulates_failures_across_stages() -> None:
    result = run_box_ci(
        FakeForge(),
        7,
        repo_path=REPO,
        verifier=_red_verifier,
        sanitiser=lambda text: False,
        runner=_clean_git(),
    )

    assert result.green is False
    assert len(result.failures) == 2


def test_make_box_ci_runner_binds_repo_path_and_overrides() -> None:
    seen: dict[str, Any] = {}

    def verifier(repo_path: Path, branch: str) -> dict:
        seen["repo_path"] = repo_path
        seen["branch"] = branch
        return _green_verifier(repo_path, branch)

    runner = make_box_ci_runner(
        "/some/clone", verifier=verifier, sanitiser=lambda text: True, runner=_clean_git()
    )
    result = runner(FakeForge(), 7)

    assert result.green is True
    assert seen["repo_path"] == Path("/some/clone")
    assert seen["branch"] == "bot/impl-7"
