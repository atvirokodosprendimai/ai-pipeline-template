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
    assert cfg.max_escalation_attempts == 2
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


def test_zero_config_synthesizes_default_profile_matching_goose_fields() -> None:
    # R7: with no MODEL_REGISTRY env, routing falls back to a single 'default'
    # profile built from the goose_* fields — pipeline behaves as before.
    cfg = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
            "ZAI_API_KEY": "zai",
        }
    )
    assert set(cfg.model_registry) == {"default"}
    default = cfg.model_registry["default"]
    assert default.provider == cfg.goose_provider
    assert default.model == cfg.goose_model
    assert default.billing == "native"
    assert default.credential_env == "ZAI_API_KEY"
    assert default.host == cfg.anthropic_host
    assert cfg.stage_routing == {}
    assert cfg.max_escalation_attempts == 2


def test_explicit_registry_and_routing_parse_into_config() -> None:
    cfg = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
            "MODEL_REGISTRY": (
                '{"cheap": {"provider": "anthropic", "model": "GLM-4.7", "billing": "native",'
                ' "credential_env": "ZAI_API_KEY", "host": "https://api.z.ai/api/anthropic"},'
                ' "capable": {"provider": "openrouter", "model": "deepseek/v3",'
                ' "billing": "openrouter", "credential_env": "OPENROUTER_API_KEY"}}'
            ),
            "STAGE_ROUTING": '{"spec": "cheap", "implement": "capable"}',
        }
    )
    assert set(cfg.model_registry) == {"cheap", "capable"}
    assert cfg.stage_routing == {"spec": ("cheap",), "implement": ("capable",)}
    # explicit registry is NOT overwritten by the zero-config default
    assert "default" not in cfg.model_registry


def test_max_escalation_attempts_unset_defaults_and_invalid_values_raise() -> None:
    cfg = load_config({"TARGET_REPO": "atvirokodosprendimai/wgmesh", "DATABASE_MODE": "local"})
    assert cfg.max_escalation_attempts == 2

    with pytest.raises(ValueError, match="MAX_ESCALATION_ATTEMPTS must be an integer"):
        load_config(
            {
                "TARGET_REPO": "atvirokodosprendimai/wgmesh",
                "DATABASE_MODE": "local",
                "MAX_ESCALATION_ATTEMPTS": "nope",
            }
        )

    with pytest.raises(ValueError, match="MAX_ESCALATION_ATTEMPTS must be positive"):
        load_config(
            {
                "TARGET_REPO": "atvirokodosprendimai/wgmesh",
                "DATABASE_MODE": "local",
                "MAX_ESCALATION_ATTEMPTS": "0",
            }
        )


def test_malformed_registry_env_fails_loud() -> None:
    with pytest.raises(ValueError, match="MODEL_REGISTRY"):
        load_config(
            {
                "TARGET_REPO": "atvirokodosprendimai/wgmesh",
                "DATABASE_MODE": "local",
                "MODEL_REGISTRY": "{bad json",
            }
        )


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
