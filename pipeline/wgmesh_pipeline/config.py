from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from wgmesh_pipeline.models import (
    ModelProfile,
    parse_registry,
    parse_stage_routing,
)


VALID_MODES = frozenset({"shadow", "spec-only", "live"})
VALID_DB_MODES = frozenset({"local", "turso"})
DEFAULT_ANTHROPIC_HOST = "https://api.z.ai/api/anthropic"
DEFAULT_TARGET_REPO = "atvirokodosprendimai/wgmesh"
DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_MAX_FILES = 20
DEFAULT_REPO_PATH = "/opt/wgmesh-checkout"
DEFAULT_RECIPES_DIR = str(Path(__file__).resolve().parents[1] / "recipes")
DEFAULT_GOOSE_PROVIDER = "anthropic"
DEFAULT_GOOSE_MODEL = "GLM-4.7"
DEFAULT_MAX_ESCALATION_ATTEMPTS = 2


@dataclass(frozen=True)
class Config:
    target_repo: str
    mode: str = "shadow"
    wgmesh_bot_pat: str | None = None
    zai_api_key: str | None = None
    anthropic_host: str = DEFAULT_ANTHROPIC_HOST
    langsmith_api_key: str | None = None
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    max_files: int = DEFAULT_MAX_FILES
    repo_path: str = DEFAULT_REPO_PATH
    recipes_dir: str = DEFAULT_RECIPES_DIR
    goose_provider: str = DEFAULT_GOOSE_PROVIDER
    goose_model: str = DEFAULT_GOOSE_MODEL
    forge_kind: str = "github"
    database_mode: str = "local"
    database_path: str = "pipeline/state.db"
    turso_url: str | None = None
    turso_auth_token: str | None = None
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    # Multi-model routing (price/perf #2). Empty by default → callers synthesize
    # a zero-config default profile from the goose_* fields above (R7).
    model_registry: Mapping[str, ModelProfile] = field(default_factory=dict)
    stage_routing: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    max_escalation_attempts: int = DEFAULT_MAX_ESCALATION_ATTEMPTS

    @property
    def owner(self) -> str:
        return self.target_repo.split("/", 1)[0]

    @property
    def repo(self) -> str:
        return self.target_repo.split("/", 1)[1]


def load_config(env: Mapping[str, str] | None = None) -> Config:
    source = os.environ if env is None else env

    target_repo = _required(source, "TARGET_REPO")
    mode = _get_nonempty(source, "PIPELINE_MODE") or "shadow"
    if mode not in VALID_MODES:
        valid = ", ".join(sorted(VALID_MODES))
        raise ValueError(f"PIPELINE_MODE must be one of: {valid}; got {mode!r}")

    if "/" not in target_repo or target_repo.count("/") != 1:
        raise ValueError("TARGET_REPO must be in owner/repo form")

    pat = _get_nonempty(source, "WGMESH_BOT_PAT")
    if mode == "live" and not pat:
        raise ValueError("WGMESH_BOT_PAT is required when PIPELINE_MODE=live")

    # Explicit database selection — no silent fallback (mailservice lesson: a
    # misconfigured deploy must fail, not silently write to a local file).
    db_mode = _required(source, "DATABASE_MODE").lower()
    if db_mode not in VALID_DB_MODES:
        valid = ", ".join(sorted(VALID_DB_MODES))
        raise ValueError(f"DATABASE_MODE must be one of: {valid}; got {db_mode!r}")
    turso_url = _get_nonempty(source, "TURSO_DATABASE_URL")
    turso_token = _get_nonempty(source, "TURSO_AUTH_TOKEN")
    if db_mode == "turso" and not turso_url:
        raise ValueError("DATABASE_MODE=turso requires TURSO_DATABASE_URL")

    goose_provider = _get_nonempty(source, "GOOSE_PROVIDER") or DEFAULT_GOOSE_PROVIDER
    goose_model = _get_nonempty(source, "GOOSE_MODEL") or DEFAULT_GOOSE_MODEL
    anthropic_host = _get_nonempty(source, "ANTHROPIC_HOST") or DEFAULT_ANTHROPIC_HOST
    model_registry, stage_routing = _build_routing(
        source,
        goose_provider=goose_provider,
        goose_model=goose_model,
        anthropic_host=anthropic_host,
    )

    return Config(
        target_repo=target_repo,
        mode=mode,
        wgmesh_bot_pat=pat,
        zai_api_key=_get_nonempty(source, "ZAI_API_KEY"),
        anthropic_host=anthropic_host,
        langsmith_api_key=_get_nonempty(source, "LANGSMITH_API_KEY"),
        forge_kind=_get_nonempty(source, "FORGE_KIND") or "github",
        poll_interval_seconds=_get_int(source, "POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS),
        max_files=_get_int(source, "MAX_FILES", DEFAULT_MAX_FILES),
        repo_path=_get_nonempty(source, "WGMESH_CHECKOUT_PATH") or DEFAULT_REPO_PATH,
        recipes_dir=_get_nonempty(source, "RECIPES_DIR") or DEFAULT_RECIPES_DIR,
        goose_provider=goose_provider,
        goose_model=goose_model,
        database_mode=db_mode,
        database_path=_get_nonempty(source, "PIPELINE_DB_PATH") or "pipeline/state.db",
        turso_url=turso_url,
        turso_auth_token=turso_token,
        langfuse_host=_get_nonempty(source, "LANGFUSE_HOST"),
        langfuse_public_key=_get_nonempty(source, "LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=_get_nonempty(source, "LANGFUSE_SECRET_KEY"),
        model_registry=model_registry,
        stage_routing=stage_routing,
        max_escalation_attempts=_get_int(
            source,
            "MAX_ESCALATION_ATTEMPTS",
            DEFAULT_MAX_ESCALATION_ATTEMPTS,
        ),
    )


# Goose provider id the zero-config fallback profile uses ANTHROPIC_API_KEY for.
_DEFAULT_CREDENTIAL_ENV = "ZAI_API_KEY"


def _build_routing(
    source: Mapping[str, str],
    *,
    goose_provider: str,
    goose_model: str,
    anthropic_host: str,
) -> tuple[Mapping[str, ModelProfile], Mapping[str, tuple[str, ...]]]:
    """Registry + stage map from env, with a zero-config fallback (R7).

    When MODEL_REGISTRY is unset, synthesize a single ``default`` profile from
    the goose_* fields so the pipeline behaves exactly as it did before routing
    existed: one model, every stage. When set, parse both and trust the
    fail-closed validation in models.py (an unset STAGE_ROUTING is valid as long
    as the registry carries a ``default`` profile)."""
    registry = parse_registry(_get_nonempty(source, "MODEL_REGISTRY"))
    routing = parse_stage_routing(_get_nonempty(source, "STAGE_ROUTING"))
    if not registry:
        registry = {
            "default": ModelProfile(
                key="default",
                provider=goose_provider,
                model=goose_model,
                billing="native",
                credential_env=_DEFAULT_CREDENTIAL_ENV,
                host=anthropic_host,
            )
        }
    return registry, routing


def _required(env: Mapping[str, str], name: str) -> str:
    value = _get_nonempty(env, name)
    if value is None:
        raise ValueError(f"{name} is required")
    return value


def _get_nonempty(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _get_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _get_nonempty(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value
