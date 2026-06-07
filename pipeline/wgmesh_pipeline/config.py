from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


VALID_MODES = frozenset({"shadow", "spec-only", "live"})
DEFAULT_ANTHROPIC_HOST = "https://api.z.ai/api/anthropic"
DEFAULT_TARGET_REPO = "atvirokodosprendimai/wgmesh"
DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_MAX_FILES = 20


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
    database_path: str = "pipeline/state.db"

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

    return Config(
        target_repo=target_repo,
        mode=mode,
        wgmesh_bot_pat=pat,
        zai_api_key=_get_nonempty(source, "ZAI_API_KEY"),
        anthropic_host=_get_nonempty(source, "ANTHROPIC_HOST") or DEFAULT_ANTHROPIC_HOST,
        langsmith_api_key=_get_nonempty(source, "LANGSMITH_API_KEY"),
        poll_interval_seconds=_get_int(source, "POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS),
        max_files=_get_int(source, "MAX_FILES", DEFAULT_MAX_FILES),
        database_path=_get_nonempty(source, "PIPELINE_DB_PATH") or "pipeline/state.db",
    )


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

