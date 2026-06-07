from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from wgmesh_pipeline.config import Config


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
_KNOWN_SECRET_NAMES = frozenset(
    {"WGMESH_BOT_PAT", "BOT_PAT", "GH_PAT", "HCLOUD_TOKEN", "OPENROUTER_API_KEY"}
)


def _is_secret_var(name: str) -> bool:
    upper = name.upper()
    if upper in _KNOWN_SECRET_NAMES:
        return True
    return any(marker in upper for marker in _SECRET_MARKERS)


def build_goose_env(config: Config, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Subprocess env for Goose with all secret-shaped vars stripped, then the
    single LLM credential Goose needs added back explicitly."""
    source = os.environ if base_env is None else base_env
    env = {key: value for key, value in source.items() if not _is_secret_var(key)}
    if config.zai_api_key:
        env["ANTHROPIC_API_KEY"] = config.zai_api_key
    env["ANTHROPIC_HOST"] = config.anthropic_host
    return env


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

    def run_recipe(
        self,
        *,
        recipe: str | Path,
        workdir: str | Path,
        params: Mapping[str, str],
        expected_output: str | Path,
    ) -> GooseResult:
        workdir_path = Path(workdir)
        output_path = Path(expected_output)
        if not output_path.is_absolute():
            output_path = workdir_path / output_path

        command = ["goose", "run", "--no-session", "--recipe", str(recipe)]
        for key, value in params.items():
            command.extend(["--params", f"{key}={value}"])

        env = build_goose_env(self.config)

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
