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


def test_build_goose_env_allowlist_drops_secrets_keeps_safe_and_llm_cred() -> None:
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/bot",
        "LC_ALL": "C.UTF-8",
        "SSL_CERT_FILE": "/etc/ssl/cert.pem",
        "SSH_AUTH_SOCK": "/run/ssh",
        "WGMESH_BOT_PAT": "ghp_secret",
        "LANGSMITH_API_KEY": "ls-secret",
        "GITHUB_TOKEN": "tok",
        "APP_PRIVATE_KEY": "-----BEGIN-----",
        "DB_PASSWORD": "hunter2",
        # fail-closed cases: real credentials whose NAME carries no secret marker
        "NPM_AUTH": "npm-cred",
        "SENTRY_DSN": "https://abc@sentry.io/1",
        "PAT": "bare-pat",
    }
    env = build_goose_env(_Cfg(), base_env=base)

    # allowlisted safe vars retained (PATH/HOME/locale/TLS/ssh-agent)
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/bot"
    assert env["LC_ALL"] == "C.UTF-8"
    assert env["SSL_CERT_FILE"] == "/etc/ssl/cert.pem"
    assert env["SSH_AUTH_SOCK"] == "/run/ssh"
    # EVERYTHING not allowlisted is dropped — incl. marker-less credentials
    for leaked in (
        "WGMESH_BOT_PAT", "LANGSMITH_API_KEY", "GITHUB_TOKEN", "APP_PRIVATE_KEY",
        "DB_PASSWORD", "NPM_AUTH", "SENTRY_DSN", "PAT",
    ):
        assert leaked not in env
    # the single LLM credential Goose needs is added back explicitly
    assert env["ANTHROPIC_API_KEY"] == "zai-secret"
    assert env["ANTHROPIC_HOST"].endswith("/anthropic")
    assert env["GOOSE_PROVIDER"] == "anthropic"
    assert env["GOOSE_MODEL"]


def test_build_goose_env_only_anthropic_key_is_secret_shaped() -> None:
    # Property: nothing secret-shaped leaks. The only secret in the output is the
    # explicitly re-added LLM credential.
    base = {
        "PATH": "/usr/bin", "HOME": "/h", "FOO_TOKEN": "x", "BAR_SECRET": "y",
        "RANDOM_THING": "z", "AWS_SECRET_ACCESS_KEY": "k",
    }
    env = build_goose_env(_Cfg(), base_env=base)
    for key in env:
        assert key == "ANTHROPIC_API_KEY" or not _is_secret_var(key)


def test_build_goose_env_without_zai_key_omits_anthropic_key() -> None:
    env = build_goose_env(_Cfg(zai_api_key=None), base_env={"PATH": "/usr/bin"})
    assert "ANTHROPIC_API_KEY" not in env
    assert env["ANTHROPIC_HOST"]


def test_build_goose_env_prefers_explicit_goose_provider_model_from_base_env() -> None:
    env = build_goose_env(
        _Cfg(),
        base_env={
            "PATH": "/usr/bin",
            "GOOSE_PROVIDER": "anthropic",
            "GOOSE_MODEL": "custom-zai-model",
        },
    )

    assert env["GOOSE_PROVIDER"] == "anthropic"
    assert env["GOOSE_MODEL"] == "custom-zai-model"


def test_build_goose_env_passes_langfuse_creds_for_cost_capture() -> None:
    """Goose gets LANGFUSE_URL/PUBLIC_KEY/SECRET_KEY so it exports its own LLM
    generations (model + token usage + cost) to Langfuse — the price half of
    price/performance. SECRET_KEY is re-added past the allowlist."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _LfCfg:
        zai_api_key: str | None = "zai-secret"
        anthropic_host: str = "https://api.z.ai/api/anthropic"
        langfuse_host: str | None = "http://lf:3000"
        langfuse_public_key: str | None = "pk-lf-x"
        langfuse_secret_key: str | None = "sk-lf-x"

    env = build_goose_env(_LfCfg(), base_env={"PATH": "/usr/bin"})
    assert env["LANGFUSE_URL"] == "http://lf:3000"
    assert env["LANGFUSE_PUBLIC_KEY"] == "pk-lf-x"
    assert env["LANGFUSE_SECRET_KEY"] == "sk-lf-x"


def test_build_goose_env_omits_langfuse_when_unconfigured() -> None:
    env = build_goose_env(_Cfg(), base_env={"PATH": "/usr/bin"})
    assert "LANGFUSE_URL" not in env
    assert "LANGFUSE_SECRET_KEY" not in env
