from __future__ import annotations

from dataclasses import dataclass

from wgmesh_pipeline.goose.runner import _is_secret_var, build_goose_env


@dataclass(frozen=True)
class _Cfg:
    zai_api_key: str | None = "zai-secret"
    anthropic_host: str = "https://api.z.ai/api/anthropic"


def test_secret_vars_detected() -> None:
    for name in (
        "WGMESH_BOT_PAT",  # caught by explicit known-names set (no marker, PAT~PATH)
        "LANGSMITH_API_KEY",
        "GITHUB_TOKEN",
        "APP_PRIVATE_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "DB_PASSWORD",
        "SOME_CREDENTIAL",
        "HCLOUD_TOKEN",
    ):
        assert _is_secret_var(name) is True
    # plain non-secret vars are kept — PATH must NOT be mistaken for a PAT
    for name in ("PATH", "HOME", "LANG", "TERM", "SHELL"):
        assert _is_secret_var(name) is False


def test_build_goose_env_strips_secrets_keeps_llm_cred() -> None:
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/bot",
        "WGMESH_BOT_PAT": "ghp_secret",
        "LANGSMITH_API_KEY": "ls-secret",
        "GITHUB_TOKEN": "tok",
        "APP_PRIVATE_KEY": "-----BEGIN-----",
        "DB_PASSWORD": "hunter2",
    }
    env = build_goose_env(_Cfg(), base_env=base)

    # safe vars retained
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/bot"
    # every secret-shaped var stripped — the agent never sees them
    assert "WGMESH_BOT_PAT" not in env
    assert "LANGSMITH_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert "APP_PRIVATE_KEY" not in env
    assert "DB_PASSWORD" not in env
    # the single LLM credential Goose needs is added back explicitly
    assert env["ANTHROPIC_API_KEY"] == "zai-secret"
    assert env["ANTHROPIC_HOST"].endswith("/anthropic")


def test_build_goose_env_without_zai_key_omits_anthropic_key() -> None:
    env = build_goose_env(_Cfg(zai_api_key=None), base_env={"PATH": "/usr/bin"})
    assert "ANTHROPIC_API_KEY" not in env
    assert env["ANTHROPIC_HOST"]
