from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable, TextIO

from wgmesh_pipeline.config import Config, load_config
from wgmesh_pipeline.langchain_agent.runner import (
    ClientFactory,
    LangchainAgentRunner,
)

_LOGGER = logging.getLogger(__name__)
_DIFF_LIMIT_CHARS = 8_000

ConfigLoader = Callable[[], Config]
RunnerFactory = Callable[[Config], LangchainAgentRunner]


def main(
    argv: list[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
    runner_factory: RunnerFactory | None = None,
    config_loader: ConfigLoader = load_config,
    stdout: TextIO | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)
    args = _parse_args(argv)
    out = stdout or sys.stdout
    workdir = Path(args.workdir).resolve()
    spec_file = _spec_file_arg(Path(args.spec), workdir)

    config = config_loader()
    if args.model:
        config = replace(
            config,
            goose_model=args.model,
            model_registry={},
            stage_routing={},
        )

    runner = (
        runner_factory(config)
        if runner_factory is not None
        else LangchainAgentRunner(config, client_factory=client_factory)
    )
    result = runner.run_recipe(
        recipe=Path(config.recipes_dir) / "wgmesh-implementation.yaml",
        workdir=workdir,
        params={
            "spec_file": spec_file,
            "diff_file": "pipeline-output/replay.diff",
        },
        expected_output="pipeline-output/replay.diff",
        stage="implement",
        tier=0,
        session_id="replay",
    )
    dirty = _workspace_is_dirty(workdir)
    diff = _bounded(_git_diff(workdir))
    _print_report(
        stdout=out,
        model=config.goose_model,
        ok=result.ok,
        error=result.error,
        dirty=dirty,
        diff=diff,
        usage=result.usage,
    )
    return 0 if result.ok and dirty else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay the LangChain implementer.")
    parser.add_argument("--spec", required=True, help="Spec file path.")
    parser.add_argument("--workdir", required=True, help="Isolated git working tree.")
    parser.add_argument("--model", help="Override the implement model id.")
    return parser.parse_args(argv)


def _spec_file_arg(spec_path: Path, workdir: Path) -> str:
    if not spec_path.is_absolute():
        spec_path = (Path.cwd() / spec_path).resolve()
    else:
        spec_path = spec_path.resolve()
    try:
        return spec_path.relative_to(workdir).as_posix()
    except ValueError:
        return str(spec_path)


def _workspace_is_dirty(workdir: Path) -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workdir,
        text=True,
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        _LOGGER.warning(
            "could not inspect git status: %s",
            completed.stderr.strip() or completed.stdout.strip(),
        )
        return False
    return bool(completed.stdout.strip())


def _git_diff(workdir: Path) -> str:
    completed = subprocess.run(
        ["git", "diff", "--"],
        cwd=workdir,
        text=True,
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return completed.stderr.strip() or completed.stdout.strip()
    return completed.stdout


def _bounded(text: str) -> str:
    if len(text) <= _DIFF_LIMIT_CHARS:
        return text
    omitted = len(text) - _DIFF_LIMIT_CHARS
    return f"{text[:_DIFF_LIMIT_CHARS]}\n...[truncated {omitted} chars]...\n"


def _print_report(
    *,
    stdout: TextIO,
    model: str,
    ok: bool,
    error: str | None,
    dirty: bool,
    diff: str,
    usage: object,
) -> None:
    print("REPORT", file=stdout)
    print(f"model: {model}", file=stdout)
    print(f"ok: {ok}", file=stdout)
    print(f"error: {error}", file=stdout)
    print(f"git_dirty: {dirty}", file=stdout)
    print(f"usage: {usage}", file=stdout)
    print("diff:", file=stdout)
    print(diff or "(empty)", file=stdout)


if __name__ == "__main__":
    raise SystemExit(main())
