from __future__ import annotations

import dataclasses

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.protocol import Forge, ForgeIssue
from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue


def test_github_client_satisfies_forge_protocol() -> None:
    client = GitHubClient(Config(target_repo="atvirokodosprendimai/wgmesh"))

    assert isinstance(client, Forge)


def test_forge_issue_is_frozen() -> None:
    issue = ForgeIssue(number=1, title="t", labels=(), state="open")

    with pytest.raises(dataclasses.FrozenInstanceError):
        issue.title = "changed"  # type: ignore[misc]


def test_github_issue_is_the_forge_issue() -> None:
    """GitHubIssue stays importable as a backwards-compatible alias so the
    host-neutral dataclass has one definition."""
    assert GitHubIssue is ForgeIssue


def test_forge_protocol_declares_get_pr_mergeable() -> None:
    """Conflict-heal reads mergeability through the protocol, not raw dicts."""
    assert hasattr(Forge, "get_pr_mergeable")


def test_gitea_forge_satisfies_get_pr_mergeable() -> None:
    from wgmesh_pipeline.forge.gitea import GiteaForge

    assert hasattr(GiteaForge, "get_pr_mergeable")
