from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.config import load_config
from wgmesh_pipeline.goose.runner import GooseRunner
from wgmesh_pipeline.graph.nodes.implement import implement_node
from wgmesh_pipeline.github.client import GitHubIssue


_REGISTRY = (
    '{"cheap": {"provider": "anthropic", "model": "GLM-4.7", "billing": "native",'
    ' "credential_env": "ZAI_API_KEY", "host": "https://api.z.ai/api/anthropic"},'
    ' "capable": {"provider": "openrouter", "model": "deepseek/deepseek-chat",'
    ' "billing": "openrouter", "credential_env": "OPENROUTER_API_KEY"},'
    ' "premium": {"provider": "openrouter", "model": "openai/gpt-5",'
    ' "billing": "openrouter", "credential_env": "OPENROUTER_API_KEY"}}'
)

_OVERRIDE_REGISTRY = (
    '{"spec-model": {"provider": "openrouter", "model": "deepseek/deepseek-v3.2",'
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


def _override_config(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    return load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
            "MODEL_REGISTRY": _OVERRIDE_REGISTRY,
            "STAGE_ROUTING": '{"spec": "spec-model"}',
            "OPENROUTER_API_KEY": "or-key",
        }
    )


def _completed(stdout: str = "ok") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["goose"], returncode=0, stdout=stdout, stderr="")


def _capture_runner(calls: list[dict[str, Any]]):
    def run(command, **kwargs):
        recipe_path = Path(command[command.index("--recipe") + 1])
        calls.append(
            {
                "command": command,
                "env": kwargs["env"],
                "recipe_exists_at_invocation": recipe_path.exists(),
            }
        )
        out = Path(kwargs["cwd"]) / "out.txt"
        out.write_text("content")
        return _completed()

    return run


def _run(config, stage: str, tmp_path, calls):
    recipe = tmp_path / "r.yaml"
    recipe.write_text(
        "settings:\n"
        "  goose_provider: anthropic\n"
        "  goose_model: glm-4.6\n"
    )
    return GooseRunner(config, runner=_capture_runner(calls)).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "s.md"},
        expected_output="out.txt",
        stage=stage,
    )


def _run_tier(config, stage: str, tier: int, tmp_path, calls):
    recipe = tmp_path / "r.yaml"
    recipe.write_text(
        "settings:\n"
        "  goose_provider: anthropic\n"
        "  goose_model: glm-4.6\n"
    )
    return GooseRunner(config, runner=_capture_runner(calls)).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "s.md"},
        expected_output="out.txt",
        stage=stage,
        tier=tier,
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


def test_result_carries_model_key_for_attribution(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    config = _routed_config('{"spec": "cheap", "implement": "capable"}', monkeypatch)
    spec_result = _run(config, "spec", tmp_path, calls)
    impl_result = _run(config, "implement", tmp_path, calls)
    assert spec_result.model_key == "cheap"
    assert impl_result.model_key == "capable"


def test_zero_config_result_model_key_is_default(tmp_path, monkeypatch) -> None:
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
    assert result.model_key == "default"


def test_unmapped_stage_no_default_raises(tmp_path, monkeypatch) -> None:
    # registry has no 'default' and routing omits 'implement' → fail-closed.
    config = _routed_config('{"spec": "cheap"}', monkeypatch)
    calls: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="no model route for stage 'implement'"):
        _run(config, "implement", tmp_path, calls)


def test_run_recipe_resolves_third_ladder_model_for_tier_two(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    config = _routed_config('{"implement": ["cheap", "capable", "premium"]}', monkeypatch)
    result = _run_tier(config, "implement", 2, tmp_path, calls)

    assert result.ok is True
    env = calls[0]["env"]
    assert env["GOOSE_MODEL"] == "openai/gpt-5"
    assert env["OPENROUTER_API_KEY"] == "or-key"
    assert result.model_key == "premium"


def test_run_recipe_tier_defaults_to_zero(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    config = _routed_config('{"implement": ["cheap", "capable"]}', monkeypatch)
    result = _run(config, "implement", tmp_path, calls)

    assert result.ok is True
    assert calls[0]["env"]["GOOSE_MODEL"] == "GLM-4.7"
    assert result.model_key == "cheap"


def test_recipe_override_written_with_profile_model(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    config = _override_config(monkeypatch)
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        "instructions: test\n"
        "settings:\n"
        "  goose_provider: anthropic\n"
        "  goose_model: glm-4.6\n"
    )

    result = GooseRunner(config, runner=_capture_runner(calls)).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "s.md"},
        expected_output="out.txt",
        stage="spec",
    )

    assert result.ok is True
    command = calls[0]["command"]
    override_path = Path(command[command.index("--recipe") + 1])
    assert override_path == tmp_path / "pipeline-output" / "recipe-override-spec.yaml"
    assert calls[0]["recipe_exists_at_invocation"] is True
    assert override_path.exists()
    override_text = override_path.read_text()
    assert 'goose_provider: "openrouter"' in override_text
    assert 'goose_model: "deepseek/deepseek-v3.2"' in override_text
    assert "goose_provider: anthropic" in recipe.read_text()
    assert "goose_model: glm-4.6" in recipe.read_text()


def test_recipe_without_settings_gets_block_appended(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    config = _override_config(monkeypatch)
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text("instructions: test\n")

    result = GooseRunner(config, runner=_capture_runner(calls)).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "s.md"},
        expected_output="out.txt",
        stage="spec",
    )

    assert result.ok is True
    command = calls[0]["command"]
    override_path = Path(command[command.index("--recipe") + 1])
    override_text = override_path.read_text()
    assert "settings:\n" in override_text
    assert '  goose_provider: "openrouter"' in override_text
    assert '  goose_model: "deepseek/deepseek-v3.2"' in override_text


def test_no_profile_uses_original_recipe(tmp_path) -> None:
    calls: list[dict[str, Any]] = []
    config = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
            "ZAI_API_KEY": "zai-key",
        }
    )
    object.__setattr__(config, "model_registry", {})
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        "settings:\n"
        "  goose_provider: anthropic\n"
        "  goose_model: glm-4.6\n"
    )

    result = GooseRunner(config, runner=_capture_runner(calls)).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "s.md"},
        expected_output="out.txt",
        stage="spec",
    )

    assert result.ok is True
    command = calls[0]["command"]
    assert command[command.index("--recipe") + 1] == str(recipe)
    assert not (tmp_path / "pipeline-output" / "recipe-override-spec.yaml").exists()


def test_implement_node_passes_escalation_tier_to_runner(tmp_path) -> None:
    runner = _RecordingGooseRunner(tmp_path, "diff --git a/docs/a.md b/docs/a.md\n+new\n")

    result = implement_node(
        {
            "issue": GitHubIssue(number=9, title="Fix docs", labels=("needs-triage",), state="open"),
            "spec_path": "specs/issue-9-spec.md",
            "repo_path": tmp_path,
            "goose_runner": runner,
            "escalation_tier": 1,
        }
    )

    assert runner.calls[0]["tier"] == 1
    assert result["diff"] == "diff --git a/docs/a.md b/docs/a.md\n+new\n"


def test_implement_node_retry_with_stale_diff_reruns_goose(tmp_path) -> None:
    runner = _RecordingGooseRunner(tmp_path, "diff --git a/docs/new.md b/docs/new.md\n+fresh\n")

    result = implement_node(
        {
            "issue": GitHubIssue(number=10, title="Fix docs", labels=("needs-triage",), state="open"),
            "spec_path": "specs/issue-10-spec.md",
            "repo_path": tmp_path,
            "goose_runner": runner,
            "escalation_tier": 1,
            "diff": "diff --git a/docs/old.md b/docs/old.md\n+stale\n",
            "changed_files": ["docs/old.md"],
        }
    )

    assert len(runner.calls) == 1
    assert result["diff"] == "diff --git a/docs/new.md b/docs/new.md\n+fresh\n"
    assert result["changed_files"] == ["docs/new.md"]


class _RecordingGooseRunner:
    def __init__(self, tmp_path, diff: str):
        self.tmp_path = tmp_path
        self.diff = diff
        self.calls: list[dict[str, Any]] = []

    def run_recipe(self, **kwargs):
        self.calls.append(kwargs)
        output = self.tmp_path / kwargs["expected_output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.diff)
        return type(
            "Result",
            (),
            {
                "ok": True,
                "output_path": output,
                "error": None,
                "model_key": f"tier-{kwargs['tier']}",
            },
        )()
