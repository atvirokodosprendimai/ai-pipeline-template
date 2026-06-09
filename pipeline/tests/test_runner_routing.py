from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.config import load_config
from wgmesh_pipeline.goose.runner import GooseRunner


_REGISTRY = (
    '{"cheap": {"provider": "anthropic", "model": "GLM-4.7", "billing": "native",'
    ' "credential_env": "ZAI_API_KEY", "host": "https://api.z.ai/api/anthropic"},'
    ' "capable": {"provider": "openrouter", "model": "deepseek/deepseek-chat",'
    ' "billing": "openrouter", "credential_env": "OPENROUTER_API_KEY"}}'
)


def _routed_config(routing: str, monkeypatch):
    # Credentials live in the PROCESS env on the box (the runner reads
    # os.environ at env-build time), so set them there — not just in the
    # load_config dict — to mirror production.
    monkeypatch.setenv("ZAI_API_KEY", "zai-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    return load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
            "MODEL_REGISTRY": _REGISTRY,
            "STAGE_ROUTING": routing,
            "ZAI_API_KEY": "zai-key",
            "OPENROUTER_API_KEY": "or-key",
        }
    )


def _completed(stdout: str = "ok") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["goose"], returncode=0, stdout=stdout, stderr="")


def _capture_runner(calls: list[dict[str, Any]]):
    def run(command, **kwargs):
        calls.append({"command": command, "env": kwargs["env"]})
        out = Path(kwargs["cwd"]) / "out.txt"
        out.write_text("content")
        return _completed()

    return run


def _run(config, stage: str, tmp_path, calls):
    return GooseRunner(config, runner=_capture_runner(calls)).run_recipe(
        recipe="r.yaml",
        workdir=tmp_path,
        params={"spec_file": "s.md"},
        expected_output="out.txt",
        stage=stage,
    )


def test_spec_stage_uses_cheap_model(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    config = _routed_config('{"spec": "cheap", "implement": "capable"}', monkeypatch)
    result = _run(config, "spec", tmp_path, calls)
    assert result.ok is True
    env = calls[0]["env"]
    assert env["GOOSE_MODEL"] == "GLM-4.7"
    assert env["GOOSE_PROVIDER"] == "anthropic"
    assert env["ANTHROPIC_API_KEY"] == "zai-key"


def test_implement_stage_uses_capable_model(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    config = _routed_config('{"spec": "cheap", "implement": "capable"}', monkeypatch)
    result = _run(config, "implement", tmp_path, calls)
    assert result.ok is True
    env = calls[0]["env"]
    assert env["GOOSE_MODEL"] == "deepseek/deepseek-chat"
    assert env["GOOSE_PROVIDER"] == "openrouter"
    assert env["OPENROUTER_API_KEY"] == "or-key"
    assert "ANTHROPIC_API_KEY" not in env


def test_zero_config_run_uses_default_profile(tmp_path, monkeypatch) -> None:
    # No MODEL_REGISTRY env → load_config synthesizes the 'default' profile;
    # any stage resolves to it.
    monkeypatch.setenv("ZAI_API_KEY", "zai-key")
    config = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
            "ZAI_API_KEY": "zai-key",
        }
    )
    calls: list[dict[str, Any]] = []
    result = _run(config, "implement", tmp_path, calls)
    assert result.ok is True
    env = calls[0]["env"]
    assert env["GOOSE_MODEL"]  # the default GLM model
    assert env["ANTHROPIC_API_KEY"] == "zai-key"


def test_unmapped_stage_no_default_raises(tmp_path, monkeypatch) -> None:
    # registry has no 'default' and routing omits 'implement' → fail-closed.
    config = _routed_config('{"spec": "cheap"}', monkeypatch)
    calls: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="no model route for stage 'implement'"):
        _run(config, "implement", tmp_path, calls)
