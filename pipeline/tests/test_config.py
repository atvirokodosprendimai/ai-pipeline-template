from __future__ import annotations

import json
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
    assert cfg.supervisor_live is False
    assert cfg.selfheal_live is False
    assert cfg.observation_live is False
    assert cfg.strategy_audit_live is False

    with pytest.raises(FrozenInstanceError):
        cfg.mode = "live"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("env_name", "field_name"),
    (
        ("SUPERVISOR_LIVE", "supervisor_live"),
        ("SELFHEAL_LIVE", "selfheal_live"),
        ("OBSERVATION_LIVE", "observation_live"),
        ("STRATEGY_AUDIT_LIVE", "strategy_audit_live"),
    ),
)
def test_per_module_live_flags_parse_from_env(env_name: str, field_name: str) -> None:
    cfg = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
            env_name: "true",
        }
    )

    assert getattr(cfg, field_name) is True


@pytest.mark.parametrize(
    ("env_name", "field_name"),
    (
        ("SUPERVISOR_LIVE", "supervisor_live"),
        ("SELFHEAL_LIVE", "selfheal_live"),
        ("OBSERVATION_LIVE", "observation_live"),
        ("STRATEGY_AUDIT_LIVE", "strategy_audit_live"),
    ),
)
def test_per_module_live_flags_parse_from_box_config(
    tmp_path: Path, env_name: str, field_name: str
) -> None:
    from wgmesh_pipeline.config import _read_box_config

    path = tmp_path / "box-config.json"
    path.write_text(json.dumps({env_name: "true"}), encoding="utf-8")

    cfg = load_config(
        {
            **_read_box_config(path),
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
        }
    )

    assert getattr(cfg, field_name) is True


@pytest.mark.parametrize(
    "env_name",
    (
        "SUPERVISOR_LIVE",
        "SELFHEAL_LIVE",
        "OBSERVATION_LIVE",
        "STRATEGY_AUDIT_LIVE",
    ),
)
def test_per_module_live_flags_reject_invalid_values(env_name: str) -> None:
    with pytest.raises(ValueError, match=rf"{env_name} must be 'true' or 'false'"):
        load_config(
            {
                "TARGET_REPO": "atvirokodosprendimai/wgmesh",
                "DATABASE_MODE": "local",
                env_name: "yes",
            }
        )


def test_bogus_mode_lists_valid_modes() -> None:
    with pytest.raises(ValueError, match="PIPELINE_MODE.*live.*shadow.*spec-only"):
        load_config(
            {"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "bogus"}
        )


def test_missing_target_repo_raises_with_var_name() -> None:
    with pytest.raises(ValueError, match="TARGET_REPO"):
        load_config({})


def test_shadow_allows_missing_pat_live_requires_it() -> None:
    shadow = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "PIPELINE_MODE": "shadow",
            "DATABASE_MODE": "local",
        }
    )
    assert shadow.wgmesh_bot_pat is None

    with pytest.raises(ValueError, match="WGMESH_BOT_PAT"):
        load_config(
            {
                "TARGET_REPO": "atvirokodosprendimai/wgmesh",
                "PIPELINE_MODE": "live",
                "DATABASE_MODE": "local",
            }
        )


def test_database_mode_explicit_no_silent_fallback() -> None:
    # The mailservice lesson: a misconfigured deploy must fail, not silently
    # write local. DATABASE_MODE is required and validated.
    with pytest.raises(ValueError, match="DATABASE_MODE"):
        load_config(
            {"TARGET_REPO": "atvirokodosprendimai/wgmesh", "PIPELINE_MODE": "shadow"}
        )

    with pytest.raises(ValueError, match="DATABASE_MODE"):
        load_config(
            {
                "TARGET_REPO": "atvirokodosprendimai/wgmesh",
                "PIPELINE_MODE": "shadow",
                "DATABASE_MODE": "bogus",
            }
        )

    # turso requires the URL — fail-loud, never fall back to local
    with pytest.raises(ValueError, match="TURSO_DATABASE_URL"):
        load_config(
            {
                "TARGET_REPO": "atvirokodosprendimai/wgmesh",
                "PIPELINE_MODE": "shadow",
                "DATABASE_MODE": "turso",
            }
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
    cfg = load_config(
        {"TARGET_REPO": "atvirokodosprendimai/wgmesh", "DATABASE_MODE": "local"}
    )
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


def test_read_box_config_allowlist_and_secret_rejection(tmp_path) -> None:
    from wgmesh_pipeline.config import _read_box_config

    p = tmp_path / "box-config.json"
    p.write_text(
        json.dumps(
            {
                "CONTROL_LOOP_ENABLED": "true",
                "SELFHEAL_INTERVAL_SECONDS": 900,
                "OBSERVATION_LIVE": "true",
                "_comment": "ignored",
                "WGMESH_BOT_PAT": "ghp_secret_should_be_ignored",
                "TURSO_AUTH_TOKEN": "secret",
            }
        )
    )
    cfg = _read_box_config(p)
    assert cfg == {
        "CONTROL_LOOP_ENABLED": "true",
        "SELFHEAL_INTERVAL_SECONDS": "900",
        "OBSERVATION_LIVE": "true",
    }
    assert "WGMESH_BOT_PAT" not in cfg and "TURSO_AUTH_TOKEN" not in cfg


def test_read_box_config_absent_or_malformed(tmp_path) -> None:
    from wgmesh_pipeline.config import _read_box_config

    assert _read_box_config(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert _read_box_config(bad) == {}


def test_committed_box_config_is_valid_and_allowlisted() -> None:
    # Structural guard on the real committed file — NOT its exact values, which
    # are edited as normal gitops ops (pinning them would churn CI). Asserts:
    # every honored key is in the allowlist, and any present enum/int toggles
    # carry loadable values.
    from wgmesh_pipeline.config import (
        _read_box_config,
        BOX_CONFIG_ALLOWLIST,
        VALID_CONTROL_LOOP_MODES,
    )

    cfg = _read_box_config()
    assert set(cfg).issubset(BOX_CONFIG_ALLOWLIST)
    if "CONTROL_LOOP_MODE" in cfg:
        assert cfg["CONTROL_LOOP_MODE"] in VALID_CONTROL_LOOP_MODES
    if "CONTROL_LOOP_ENABLED" in cfg:
        assert cfg["CONTROL_LOOP_ENABLED"].lower() in {
            "true",
            "false",
            "1",
            "0",
            "yes",
            "no",
        }
    for k in (
        "SUPERVISOR_LIVE",
        "SELFHEAL_LIVE",
        "OBSERVATION_LIVE",
        "STRATEGY_AUDIT_LIVE",
    ):
        if k in cfg:
            assert cfg[k].lower() in {"true", "false"}
    for k in cfg:
        if k.endswith("_SECONDS") or k == "MAX_FILES":
            assert int(cfg[k]) > 0


# --- Quackback config tests ---

_MINIMAL_ENV = {
    "TARGET_REPO": "atvirokodosprendimai/wgmesh",
    "DATABASE_MODE": "local",
}


def test_quackback_forge_with_creds_loads_successfully() -> None:
    cfg = load_config(
        {
            **_MINIMAL_ENV,
            "FORGE_KIND": "quackback",
            "QUACKBACK_URL": "https://quackback.example.com",
            "QUACKBACK_TOKEN": "secret-token",
            "QUACKBACK_BOARD_ID": "board_01abc",
        }
    )
    assert cfg.quackback_url == "https://quackback.example.com"
    assert cfg.quackback_token == "secret-token"
    assert cfg.quackback_board_id == "board_01abc"


def test_quackback_forge_missing_token_raises_value_error() -> None:
    with pytest.raises(ValueError, match="QUACKBACK"):
        load_config(
            {
                **_MINIMAL_ENV,
                "FORGE_KIND": "quackback",
                "QUACKBACK_URL": "https://quackback.example.com",
                "QUACKBACK_BOARD_ID": "board_01abc",
                # QUACKBACK_TOKEN intentionally absent
            }
        )


def test_quackback_forge_missing_board_id_raises_value_error() -> None:
    # The cutover (U2) needs the board id at config time — a misconfigured box
    # must fail loudly, not fall back to github or KeyError at first create.
    with pytest.raises(ValueError, match="QUACKBACK_BOARD_ID"):
        load_config(
            {
                **_MINIMAL_ENV,
                "FORGE_KIND": "quackback",
                "QUACKBACK_URL": "https://quackback.example.com",
                "QUACKBACK_TOKEN": "secret-token",
                # QUACKBACK_BOARD_ID intentionally absent
            }
        )


def test_quackback_board_id_passes_through_box_config_allowlist(tmp_path: Path) -> None:
    from wgmesh_pipeline.config import _read_box_config

    path = tmp_path / "box-config.json"
    path.write_text(json.dumps({"QUACKBACK_BOARD_ID": "board_01xyz"}), encoding="utf-8")
    allowed = _read_box_config(path)
    assert allowed.get("QUACKBACK_BOARD_ID") == "board_01xyz"


def test_github_forge_without_quackback_vars_is_fine() -> None:
    cfg = load_config(
        {
            **_MINIMAL_ENV,
            # FORGE_KIND defaults to github; no Quackback vars set
        }
    )
    assert cfg.quackback_url is None
