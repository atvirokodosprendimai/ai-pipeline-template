from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from wgmesh_pipeline.config import load_config


def test_full_env_loads_frozen_config_with_shadow_default() -> None:
    cfg = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
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
    assert cfg.database_mode == "local"
    assert cfg.repo_path == "/opt/wgmesh-checkout"
    assert Path(cfg.recipes_dir).name == "recipes"
    assert Path(cfg.recipes_dir).parent.name == "pipeline"

    with pytest.raises(FrozenInstanceError):
        cfg.mode = "live"  # type: ignore[misc]


def test_bogus_mode_lists_valid_modes() -> None:
    with pytest.raises(ValueError, match="PIPELINE_MODE.*live.*shadow.*spec-only"):
        load_config({"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "bogus"})


def test_missing_target_repo_raises_with_var_name() -> None:
    with pytest.raises(ValueError, match="TARGET_REPO"):
        load_config({})


def test_shadow_allows_missing_pat_live_requires_it() -> None:
    shadow = load_config(
        {"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "shadow", "DATABASE_MODE": "local"}
    )
    assert shadow.wgmesh_bot_pat is None

    with pytest.raises(ValueError, match="WGMESH_BOT_PAT"):
        load_config(
            {"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "live", "DATABASE_MODE": "local"}
        )


def test_database_mode_explicit_no_silent_fallback() -> None:
    # The mailservice lesson: a misconfigured deploy must fail, not silently
    # write local. DATABASE_MODE is required and validated.
    with pytest.raises(ValueError, match="DATABASE_MODE"):
        load_config({"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "shadow"})

    with pytest.raises(ValueError, match="DATABASE_MODE"):
        load_config(
            {"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "shadow", "DATABASE_MODE": "bogus"}
        )

    # turso requires the URL — fail-loud, never fall back to local
    with pytest.raises(ValueError, match="TURSO_DATABASE_URL"):
        load_config(
            {"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "shadow", "DATABASE_MODE": "turso"}
        )

    cfg = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "PIPELINE_MODE": "shadow",
            "DATABASE_MODE": "turso",
            "TURSO_DATABASE_URL": "libsql://db.turso.io",
            "TURSO_AUTH_TOKEN": "tok",
        }
    )
    assert cfg.database_mode == "turso"
    assert cfg.turso_url == "libsql://db.turso.io"


def test_wgmesh_checkout_path_env_and_recipes_dir_override() -> None:
    cfg = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "PIPELINE_MODE": "spec-only",
            "DATABASE_MODE": "local",
            "WGMESH_BOT_PAT": "token",
            "WGMESH_CHECKOUT_PATH": "/tmp/wgmesh",
            "RECIPES_DIR": "/tmp/recipes",
        }
    )

    assert cfg.repo_path == "/tmp/wgmesh"
    assert cfg.recipes_dir == "/tmp/recipes"
