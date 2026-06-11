from __future__ import annotations

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.factory import make_forge
from wgmesh_pipeline.forge.protocol import Forge
from wgmesh_pipeline.github.client import GitHubClient


def test_default_forge_kind_is_github() -> None:
    config = Config(target_repo="atvirokodosprendimai/wgmesh")

    forge = make_forge(config)

    assert isinstance(forge, GitHubClient)
    assert isinstance(forge, Forge)


def test_unknown_forge_kind_fails_closed() -> None:
    config = Config(target_repo="atvirokodosprendimai/wgmesh", forge_kind="sourcehut")

    with pytest.raises(ValueError, match="unknown forge_kind"):
        make_forge(config)


def test_config_reads_forge_kind_from_env() -> None:
    from wgmesh_pipeline.config import load_config

    config = load_config(
        {"TARGET_REPO": "o/r", "FORGE_KIND": "gitea", "DATABASE_MODE": "local"}
    )

    assert config.forge_kind == "gitea"
