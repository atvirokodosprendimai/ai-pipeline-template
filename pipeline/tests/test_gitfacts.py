from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wgmesh_pipeline.forge.gitfacts import (
    GitFactsUnavailable,
    has_merged_resolution_commit,
    make_resolution_lookup,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "clone"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "f").write_text("0")
    _git(repo, "add", "f")
    _git(repo, "commit", "-m", "chore: init")
    return repo


def _commit(repo: Path, title: str) -> None:
    f = repo / "f"
    f.write_text(f.read_text() + "x")
    _git(repo, "add", "f")
    _git(repo, "commit", "-m", title)


def test_merged_impl_commit_resolves(repo: Path) -> None:
    _commit(repo, "impl: Issue #540 - Goose implementation (#544)")

    assert has_merged_resolution_commit(repo, 540, branch="main") is True


def test_copilot_era_spec_suffix_resolves(repo: Path) -> None:
    _commit(repo, "spec: Add status output format (Issue #510) (#511)")

    assert has_merged_resolution_commit(repo, 510, branch="main") is True


def test_referencing_only_commit_does_not_resolve(repo: Path) -> None:
    _commit(repo, "fix: regression caused by Issue #540 rollout")

    assert has_merged_resolution_commit(repo, 540, branch="main") is False


def test_number_prefix_does_not_resolve(repo: Path) -> None:
    _commit(repo, "impl: Issue #5401 - other work")

    assert has_merged_resolution_commit(repo, 540, branch="main") is False


def test_missing_clone_raises_unavailable(tmp_path: Path) -> None:
    with pytest.raises(GitFactsUnavailable):
        has_merged_resolution_commit(tmp_path / "nope", 1, branch="main")


class _Host:
    def __init__(self, answer: bool):
        self.answer = answer
        self.calls: list[int] = []

    def has_merged_resolution_pr(self, issue_number: int) -> bool:
        self.calls.append(issue_number)
        return self.answer


def test_lookup_git_hit_skips_host(repo: Path) -> None:
    _commit(repo, "impl: Issue #7 - done (#8)")
    host = _Host(answer=False)

    lookup = make_resolution_lookup(repo, host, branch="main")

    assert lookup(7) is True
    assert host.calls == []


def test_lookup_git_miss_falls_back_to_host(repo: Path) -> None:
    host = _Host(answer=True)

    lookup = make_resolution_lookup(repo, host, branch="main")

    assert lookup(9) is True
    assert host.calls == [9]


def test_lookup_git_unavailable_falls_back_to_host(tmp_path: Path) -> None:
    host = _Host(answer=False)

    lookup = make_resolution_lookup(tmp_path / "missing", host, branch="main")

    assert lookup(3) is False
    assert host.calls == [3]
