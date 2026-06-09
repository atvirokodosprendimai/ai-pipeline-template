from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from wgmesh_pipeline.config import Config, DEFAULT_GOOSE_MODEL, DEFAULT_GOOSE_PROVIDER
from wgmesh_pipeline.models import ModelProfile, credential_for, resolve_profile


SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]
GOOSE_TIMEOUT_SECONDS = 1800

# Substrings that mark an env var as secret. Goose is an LLM agent — it must NOT
# inherit the box's PAT, LangSmith key, or any other credential (it could echo
# them into output or logs). We strip every secret-shaped var and then add back
# ONLY the LLM credential Goose legitimately needs. (Borrowed from the Attractor
# coding-agent spec: exclude sensitive env vars from the agent by default.)
_SECRET_MARKERS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "API_KEY",
    "ACCESS_KEY",
    "APP_KEY",
)

# Known sensitive var names that the substring markers miss — notably
# WGMESH_BOT_PAT (the box's GitHub token; "PAT" can't be a marker because it
# would also strip PATH).
# Provider API keys all match the "API_KEY" marker already, but list the
# multi-model routing creds explicitly so the intent is documented and a future
# marker refactor can't silently fail-open on them (R6).
_KNOWN_SECRET_NAMES = frozenset(
    {
        "WGMESH_BOT_PAT",
        "BOT_PAT",
        "GH_PAT",
        "HCLOUD_TOKEN",
        "OPENROUTER_API_KEY",
        "MINIMAX_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
    }
)


def _is_secret_var(name: str) -> bool:
    upper = name.upper()
    if upper in _KNOWN_SECRET_NAMES:
        return True
    return any(marker in upper for marker in _SECRET_MARKERS)


# ALLOWLIST (fail-closed): Goose's subprocess env is built from {} by copying
# ONLY these known-safe vars, then adding the LLM credential. A denylist over an
# unbounded env namespace is fail-open — a future/ambient credential with no
# secret-marker in its name would leak to the LLM agent. The allowlist drops
# anything not explicitly named. Goose needs to find its binary + tools (PATH),
# its config/keyring (HOME), reach z.ai over TLS (SSL_CERT_*), and basic locale.
# It does NOT push git — our GitHubClient does that with the PAT — so no GIT_/
# auth vars are passed.
_SAFE_ENV_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "TERM",
        "SHELL",
        "TZ",
        "TMPDIR",
        "TMP",
        "TEMP",
        "PWD",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "SSH_AUTH_SOCK",
        "NO_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "no_proxy",
        "http_proxy",
        "https_proxy",
    }
)
_SAFE_ENV_PREFIXES = ("LC_",)


def _is_safe_var(name: str) -> bool:
    return name in _SAFE_ENV_NAMES or name.startswith(_SAFE_ENV_PREFIXES)


def build_goose_env(
    config: Config,
    base_env: Mapping[str, str] | None = None,
    *,
    profile: ModelProfile | None = None,
) -> dict[str, str]:
    """Subprocess env for Goose: fail-closed allowlist of known-safe vars, then
    the single LLM credential the selected model needs added back explicitly.
    Anything not on the allowlist (incl. the box's PAT and any unknown secret)
    is dropped — the LLM agent never sees it.

    When ``profile`` is given, the model's provider/model/credential/host come
    from that profile and the credential value is read from the (filtered)
    source env named by ``profile.credential_env``. This is what lets multiple
    providers — including two Anthropic-family models (z.ai and real Anthropic)
    — coexist in one process: each call writes only its OWN credential, so there
    is no global ANTHROPIC_API_KEY hijack.

    When ``profile`` is None, the legacy zero-config behavior applies (single
    z.ai model from the config fields) so existing call sites are unchanged."""
    source = os.environ if base_env is None else base_env
    env = {key: value for key, value in source.items() if _is_safe_var(key)}
    if profile is None:
        _apply_legacy_default(env, config, source)
    else:
        _apply_profile(env, profile, source)
    _apply_langfuse(env, config)
    return env


def _apply_legacy_default(env: dict[str, str], config: Config, source: Mapping[str, str]) -> None:
    """Pre-routing behavior: one z.ai model from config, provider/model
    overridable via the source env. Kept verbatim for backward compatibility."""
    if config.zai_api_key:
        env["ANTHROPIC_API_KEY"] = config.zai_api_key
    env["ANTHROPIC_HOST"] = config.anthropic_host
    env["GOOSE_PROVIDER"] = source.get("GOOSE_PROVIDER") or getattr(config, "goose_provider", DEFAULT_GOOSE_PROVIDER)
    env["GOOSE_MODEL"] = source.get("GOOSE_MODEL") or getattr(config, "goose_model", DEFAULT_GOOSE_MODEL)


def _apply_profile(env: dict[str, str], profile: ModelProfile, source: Mapping[str, str]) -> None:
    """Profile-driven model selection. Fail-closed: an unsupported provider/
    billing combo or a missing credential raises rather than silently running
    Goose against the wrong (or no) model."""
    env["GOOSE_PROVIDER"] = profile.provider
    env["GOOSE_MODEL"] = profile.model
    cred = credential_for(profile, source)  # raises if the named var is unset
    if profile.billing == "openrouter":
        env["OPENROUTER_API_KEY"] = cred
    elif profile.billing == "native" and profile.provider == "anthropic":
        # z.ai today, real Anthropic later — distinguished only by host + key,
        # both written per-call so the two never collide.
        env["ANTHROPIC_API_KEY"] = cred
        if profile.host:
            env["ANTHROPIC_HOST"] = profile.host
    else:
        raise ValueError(
            f"model profile {profile.key!r}: unsupported native provider "
            f"{profile.provider!r}; route it via OpenRouter (billing='openrouter')"
        )


def _apply_langfuse(env: dict[str, str], config: Config) -> None:
    # Cost-capture: hand Goose the Langfuse creds so it exports its OWN LLM
    # generations (model + token usage + cost) to Langfuse -> populates the
    # per-model cost dashboards (the price half of price/performance routing).
    # The allowlist strips LANGFUSE_SECRET_KEY by default, so re-add explicitly.
    # goose expects LANGFUSE_URL (not LANGFUSE_HOST).
    lf_host = getattr(config, "langfuse_host", None)
    lf_pub = getattr(config, "langfuse_public_key", None)
    lf_sec = getattr(config, "langfuse_secret_key", None)
    if lf_host and lf_pub and lf_sec:
        env["LANGFUSE_URL"] = lf_host
        env["LANGFUSE_PUBLIC_KEY"] = lf_pub
        env["LANGFUSE_SECRET_KEY"] = lf_sec


@dataclass(frozen=True)
class GooseResult:
    ok: bool
    output_path: Path | None
    duration_seconds: float
    raw_log: str
    error: str | None = None


class GooseRunner:
    def __init__(self, config: Config, *, runner: SubprocessRunner | None = None):
        self.config = config
        self._runner = runner or subprocess.run

    def _resolve_profile(self, stage: str | None) -> ModelProfile | None:
        """Pick the model profile for ``stage`` from the config registry/map.

        Returns None when no stage is given or the config carries no registry
        (e.g. minimal test configs) — build_goose_env then uses the legacy
        single-model path. When a registry IS present, resolution is fail-closed
        (an unroutable stage raises in resolve_profile)."""
        registry = getattr(self.config, "model_registry", {}) or {}
        routing = getattr(self.config, "stage_routing", {}) or {}
        if stage is None or not registry:
            return None
        return resolve_profile(registry, routing, stage)

    def run_recipe(
        self,
        *,
        recipe: str | Path,
        workdir: str | Path,
        params: Mapping[str, str],
        expected_output: str | Path,
        stage: str | None = None,
    ) -> GooseResult:
        workdir_path = Path(workdir)
        output_path = Path(expected_output)
        if not output_path.is_absolute():
            output_path = workdir_path / output_path

        command = ["goose", "run", "--no-session", "--recipe", str(recipe)]
        for key, value in params.items():
            command.extend(["--params", f"{key}={value}"])

        env = build_goose_env(self.config, profile=self._resolve_profile(stage))

        started = time.monotonic()
        try:
            completed = self._runner(
                command,
                cwd=str(workdir_path),
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=GOOSE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            return GooseResult(
                ok=False,
                output_path=None,
                duration_seconds=duration,
                raw_log=_join_log(_decode_timeout_output(exc.output), _decode_timeout_output(exc.stderr)),
                error=f"goose timed out after {GOOSE_TIMEOUT_SECONDS}s",
            )
        duration = time.monotonic() - started
        raw_log = _join_log(completed.stdout, completed.stderr)

        if completed.returncode != 0:
            return GooseResult(
                ok=False,
                output_path=None,
                duration_seconds=duration,
                raw_log=raw_log,
                error=f"goose exited {completed.returncode}",
            )

        if not output_path.exists() or output_path.stat().st_size == 0:
            return GooseResult(
                ok=False,
                output_path=output_path,
                duration_seconds=duration,
                raw_log=raw_log,
                error=f"empty output guard fired for {output_path}",
            )

        return GooseResult(
            ok=True,
            output_path=output_path,
            duration_seconds=duration,
            raw_log=raw_log,
        )


def _join_log(*parts: str | None) -> str:
    return "\n".join(part for part in parts if part)


def _decode_timeout_output(value: str | bytes | None) -> str | None:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
