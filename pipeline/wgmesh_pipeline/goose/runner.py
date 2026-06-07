from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from wgmesh_pipeline.config import Config


SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


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

        env = os.environ.copy()
        if self.config.zai_api_key:
            env["ANTHROPIC_API_KEY"] = self.config.zai_api_key
        env["ANTHROPIC_HOST"] = self.config.anthropic_host

        started = time.monotonic()
        completed = self._runner(
            command,
            cwd=str(workdir_path),
            env=env,
            text=True,
            capture_output=True,
            check=False,
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

