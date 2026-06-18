"""Tests for the Executor protocol and build_executor factory."""

from __future__ import annotations

import pytest

from wgmesh_pipeline.executor import Executor, build_executor
from wgmesh_pipeline.goose.runner import GooseRunner
from wgmesh_pipeline.config import load_config
from wgmesh_pipeline.langchain_agent.runner import LangchainAgentRunner

# ---------------------------------------------------------------------------
# Minimal env dict that satisfies load_config's required fields.
# ---------------------------------------------------------------------------
_BASE_ENV = {
    "TARGET_REPO": "atvirokodosprendimai/wgmesh",
    "DATABASE_MODE": "local",
    "WGMESH_BOT_PAT": "token",
    "ZAI_API_KEY": "zai",
}


def _cfg(**extra: str) -> object:
    """Return a Config built from the base env plus any extra overrides."""
    return load_config({**_BASE_ENV, **extra})


# ---------------------------------------------------------------------------
# Factory — happy paths
# ---------------------------------------------------------------------------


def test_default_config_returns_goose_runner() -> None:
    """Default Config (EXECUTOR unset) → build_executor returns a GooseRunner."""
    cfg = _cfg()
    assert cfg.executor == "goose"
    result = build_executor(cfg)
    assert isinstance(result, GooseRunner)


def test_explicit_goose_with_fake_runner() -> None:
    """Config(executor='goose') with a stub runner forwarded → GooseRunner."""
    cfg = _cfg(EXECUTOR="goose")
    fake_runner = object()  # not called in this test
    result = build_executor(cfg, runner=fake_runner)  # type: ignore[arg-type]
    assert isinstance(result, GooseRunner)


# ---------------------------------------------------------------------------
# Factory — error paths
# ---------------------------------------------------------------------------


def test_langchain_returns_langchain_runner() -> None:
    """config.executor == 'langchain' → build_executor returns LangchainAgentRunner."""
    cfg = _cfg(EXECUTOR="langchain")
    result = build_executor(cfg)
    assert isinstance(result, LangchainAgentRunner)


def test_unknown_executor_raises_value_error() -> None:
    """Unknown executor value → ValueError (fail-closed)."""
    cfg = _cfg(EXECUTOR="bogus")
    with pytest.raises(ValueError, match="unknown executor"):
        build_executor(cfg)


# ---------------------------------------------------------------------------
# Env parsing — mixed case + whitespace
# ---------------------------------------------------------------------------


def test_executor_env_normalised_lower_strip() -> None:
    """EXECUTOR='LangChain ' (mixed case + trailing space) → config.executor == 'langchain'."""
    cfg = _cfg(EXECUTOR="LangChain ")
    assert cfg.executor == "langchain"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_goose_runner_satisfies_executor_protocol() -> None:
    """GooseRunner is structurally compatible with the Executor protocol."""
    cfg = _cfg()
    runner = build_executor(cfg)
    # runtime_checkable Protocol — isinstance works.
    assert isinstance(runner, Executor)
    # Also verify the method is present as a double-check.
    assert callable(getattr(runner, "run_recipe", None))
