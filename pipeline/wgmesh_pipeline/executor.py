"""Executor protocol and factory for wgmesh_pipeline.

Defines the ``Executor`` protocol (matching ``GooseRunner.run_recipe``) and
``build_executor(config)`` which selects the concrete implementation via
``config.executor`` (populated from the ``EXECUTOR`` env var, default "goose").

Any unknown value fails closed with ``ValueError``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from wgmesh_pipeline.goose.runner import GooseResult, GooseRunner, SubprocessRunner


@runtime_checkable
class Executor(Protocol):
    """Protocol satisfied by any executor that can run a Goose recipe.

    The signature is identical to ``GooseRunner.run_recipe`` so existing
    call sites need no changes when a different backend is substituted.
    """

    def run_recipe(
        self,
        *,
        recipe: str | Path,
        workdir: str | Path,
        params: Mapping[str, str],
        expected_output: str | Path,
        stage: str | None = None,
        tier: int = 0,
        session_id: str | None = None,
    ) -> GooseResult: ...


def build_executor(
    config: object,
    *,
    runner: SubprocessRunner | None = None,
) -> Executor:
    """Return an ``Executor`` selected by ``config.executor``.

    * ``"goose"``    → :class:`~wgmesh_pipeline.goose.runner.GooseRunner`
    * ``"langchain"``→ :class:`~wgmesh_pipeline.langchain_agent.runner.LangchainAgentRunner`
    * anything else  → raises :exc:`ValueError` (fail-closed)

    ``runner`` is forwarded to ``GooseRunner.__init__`` for test injection.
    """
    executor_name: str = getattr(config, "executor", "goose")
    if executor_name == "goose":
        return GooseRunner(config, runner=runner)  # type: ignore[arg-type]
    if executor_name == "langchain":
        from wgmesh_pipeline.langchain_agent.runner import LangchainAgentRunner

        return LangchainAgentRunner(config)  # type: ignore[arg-type]
    raise ValueError(f"unknown executor: {executor_name!r}")
