from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from wgmesh_pipeline.config import load_config


def test_full_env_loads_frozen_config_with_shadow_default() -> None:
    cfg = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "WGMESH_BOT_PAT": "token",
            "ZAI_API_KEY": "zai",
            "LANGSMITH_API_KEY": "smith",
            "POLL_INTERVAL_SECONDS": "60",
            "MAX_FILES": "5",
        }
    )

    assert cfg.mode == "shadow"
    assert cfg.target_repo == "atvirokodosprendimai/wgmesh"
    assert cfg.owner == "atvirokodosprendimai"
    assert cfg.repo == "wgmesh"
    assert cfg.poll_interval_seconds == 60
    assert cfg.max_files == 5

    with pytest.raises(FrozenInstanceError):
        cfg.mode = "live"  # type: ignore[misc]


def test_bogus_mode_lists_valid_modes() -> None:
    with pytest.raises(ValueError, match="PIPELINE_MODE.*live.*shadow.*spec-only"):
        load_config({"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "bogus"})


def test_missing_target_repo_raises_with_var_name() -> None:
    with pytest.raises(ValueError, match="TARGET_REPO"):
        load_config({})


def test_shadow_allows_missing_pat_live_requires_it() -> None:
    shadow = load_config({"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "shadow"})
    assert shadow.wgmesh_bot_pat is None

    with pytest.raises(ValueError, match="WGMESH_BOT_PAT"):
        load_config({"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "live"})

