from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.config import Config, load_config
from wgmesh_pipeline.goose.usage import UsageTotals
from wgmesh_pipeline.langchain_agent.runner import (
    MAX_TOOL_OUTPUT_CHARS,
    LangchainAgentRunner,
    _bounded,
)
from wgmesh_pipeline.models import ModelProfile

pytestmark = pytest.mark.unit


@dataclass
class FakeAIMessage:
    content: str
    tool_calls: list[dict[str, Any]]
    usage_metadata: dict[str, int]


class FakeClient:
    def __init__(self, messages: list[FakeAIMessage]):
        self._messages = messages
        self.bound_specs: list[object] | None = None
        self.invocations: list[list[Any]] = []

    def bind_tools(self, specs):
        self.bound_specs = list(specs)
        return self

    def invoke(self, messages):
        self.invocations.append(list(messages))
        if len(self._messages) == 1:
            return self._messages[0]
        return self._messages.pop(0)


def cfg() -> Config:
    return Config(
        target_repo="atvirokodosprendimai/wgmesh",
        zai_api_key="zai",
        anthropic_host="https://api.z.ai/api/anthropic",
    )


def write_recipe(tmp_path: Path, body: str | None = None) -> Path:
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        body
        or (
            "version: '1'\n" "prompt: |\n" "  Write {{ output_file }} using the tool.\n"
        ),
        encoding="utf-8",
    )
    return recipe


def init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("initial\n", encoding="utf-8")
    (tmp_path / "spec.md").write_text("Implement the change.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def test_bounded_under_budget_passthrough_and_pure() -> None:
    text = "under budget"

    assert _bounded(text) == text
    assert _bounded(text) == _bounded(text)


def test_bounded_over_budget_keeps_head_tail_and_marker() -> None:
    text = "head" + ("x" * MAX_TOOL_OUTPUT_CHARS) + "tail"
    bounded = _bounded(text)
    dropped = len(text) - MAX_TOOL_OUTPUT_CHARS

    assert len(bounded) <= MAX_TOOL_OUTPUT_CHARS + 64
    assert bounded.startswith("head")
    assert bounded.endswith("tail")
    assert f"[truncated {dropped} chars]" in bounded


def test_tool_output_is_bounded_but_raw_log_keeps_full_output(tmp_path) -> None:
    recipe = write_recipe(tmp_path)
    large_output = "head" + ("x" * MAX_TOOL_OUTPUT_CHARS) + "tail"
    (tmp_path / "large.txt").write_text(large_output, encoding="utf-8")
    fake_client: FakeClient | None = None

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        nonlocal fake_client
        fake_client = FakeClient(
            [
                FakeAIMessage(
                    content="reading",
                    tool_calls=[
                        {
                            "name": "read_file",
                            "args": {"path": "large.txt"},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                ),
                FakeAIMessage(
                    content="finished",
                    tool_calls=[],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                ),
            ]
        )
        return fake_client

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
    )

    assert result.ok is False
    assert large_output in result.raw_log
    assert fake_client is not None
    tool_message = fake_client.invocations[1][-1]
    assert tool_message.content == _bounded(large_output)
    assert tool_message.content != large_output


def test_happy_path_writes_expected_output_and_sums_usage(tmp_path) -> None:
    recipe = write_recipe(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="writing",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "out.txt", "content": "done"},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 3,
                        "total_tokens": 13,
                    },
                ),
                FakeAIMessage(
                    content="finished",
                    tool_calls=[],
                    usage_metadata={
                        "input_tokens": 4,
                        "output_tokens": 2,
                        "total_tokens": 6,
                    },
                ),
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
        stage="spec",
    )

    assert result.ok is True
    assert result.output_path == tmp_path / "out.txt"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "done"
    assert result.usage == UsageTotals(
        input_tokens=10, output_tokens=3, total_tokens=13, requests=1, skipped=0
    )
    assert result.model_key == "default"


def test_implement_stage_agent_edits_file_then_stops_returns_ok_for_dirty_workspace(
    tmp_path,
) -> None:
    recipe = write_recipe(tmp_path)
    init_git_repo(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="editing",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "implemented.txt", "content": "done\n"},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 3,
                        "total_tokens": 13,
                    },
                ),
                FakeAIMessage(
                    content="finished",
                    tool_calls=[],
                    usage_metadata={
                        "input_tokens": 4,
                        "output_tokens": 2,
                        "total_tokens": 6,
                    },
                ),
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "spec.md"},
        expected_output="diff.patch",
        stage="implement",
    )

    assert result.ok is True
    assert (tmp_path / "implemented.txt").read_text(encoding="utf-8") == "done\n"
    assert result.usage == UsageTotals(
        input_tokens=14, output_tokens=5, total_tokens=19, requests=2, skipped=0
    )


def test_implement_stage_agent_without_edits_returns_no_source_changes_error(
    tmp_path,
) -> None:
    recipe = write_recipe(tmp_path)
    init_git_repo(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="checking",
                    tool_calls=[
                        {
                            "name": "run_bash",
                            "args": {"command": "true"},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                ),
                FakeAIMessage(
                    content="finished",
                    tool_calls=[],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                ),
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "spec.md"},
        expected_output="diff.patch",
        stage="implement",
    )

    assert result.ok is False
    assert "no source changes" in (result.error or "")


def test_implement_stage_ignores_stale_diff_file_when_workspace_is_clean(
    tmp_path,
) -> None:
    recipe = write_recipe(tmp_path)
    (tmp_path / "diff.patch").write_text("stale diff\n", encoding="utf-8")
    init_git_repo(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="finished",
                    tool_calls=[],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "spec.md"},
        expected_output="diff.patch",
        stage="implement",
    )

    assert result.ok is False
    assert "no source changes" in (result.error or "")


def test_non_implement_stage_still_completes_from_expected_output(tmp_path) -> None:
    recipe = write_recipe(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="writing",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "out.txt", "content": "done"},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
        stage="spec",
    )

    assert result.ok is True


def test_emit_generation_called_with_stage_model_and_usage(
    tmp_path, monkeypatch
) -> None:
    recipe = write_recipe(tmp_path)
    init_git_repo(tmp_path)
    emitted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "wgmesh_pipeline.langchain_agent.runner.tracing.emit_generation",
        lambda **kwargs: emitted.append(kwargs),
    )

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="writing",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "out.txt", "content": "done"},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 2,
                        "total_tokens": 3,
                    },
                ),
                FakeAIMessage(
                    content="finished",
                    tool_calls=[],
                    usage_metadata={
                        "input_tokens": 4,
                        "output_tokens": 5,
                        "total_tokens": 9,
                    },
                ),
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "spec.md"},
        expected_output="diff.patch",
        stage="implement",
        session_id="issue-1",
    )

    assert result.ok is True
    assert emitted == [
        {
            "session_id": "issue-1",
            "stage": "implement",
            "model": cfg().goose_model,
            "usage": result.usage,
            "output": "finished",
        }
    ]


def test_missing_expected_output_returns_not_ok(tmp_path) -> None:
    recipe = write_recipe(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="finished",
                    tool_calls=[],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
    )

    assert result.ok is False
    assert "expected output was not written" in (result.error or "")


def test_max_iterations_default_is_40(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LANGCHAIN_MAX_ITERATIONS", raising=False)
    recipe = write_recipe(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="again",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "scratch.txt", "content": "again"},
                            "id": "call-loop",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
    )

    assert result.ok is False
    assert "max iterations (40)" in (result.error or "")
    assert result.usage is not None
    assert result.usage.requests == 40


def test_max_iterations_env_override_reports_actual_cap(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("LANGCHAIN_MAX_ITERATIONS", "3")
    recipe = write_recipe(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="again",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "scratch.txt", "content": "again"},
                            "id": "call-loop",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
    )

    assert result.ok is False
    assert "max iterations (3)" in (result.error or "")
    assert result.usage is not None
    assert result.usage.requests == 3


def test_max_iterations_invalid_env_falls_back_to_default(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("LANGCHAIN_MAX_ITERATIONS", "not-an-int")
    recipe = write_recipe(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="again",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "scratch.txt", "content": "again"},
                            "id": "call-loop",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
    )

    assert result.ok is False
    assert "max iterations (40)" in (result.error or "")
    assert result.usage is not None
    assert result.usage.requests == 40


def test_expected_output_written_mid_loop_returns_before_cap(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("LANGCHAIN_MAX_ITERATIONS", "5")
    recipe = write_recipe(tmp_path)
    fake_client: FakeClient | None = None

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        nonlocal fake_client
        fake_client = FakeClient(
            [
                FakeAIMessage(
                    content="writing",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "out.txt", "content": "diff"},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )
        return fake_client

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
    )

    assert result.ok is True
    assert fake_client is not None
    assert len(fake_client.invocations) == 1
    assert result.usage.requests == 1


def test_empty_expected_output_does_not_return_early(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("LANGCHAIN_MAX_ITERATIONS", "3")
    recipe = write_recipe(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="writing placeholder",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "out.txt", "content": ""},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
    )

    assert result.ok is False
    assert "max iterations (3)" in (result.error or "")
    assert result.usage.requests == 3


def test_model_stops_with_existing_output_still_succeeds(tmp_path) -> None:
    recipe = write_recipe(tmp_path)
    (tmp_path / "out.txt").write_text("done", encoding="utf-8")

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="finished",
                    tool_calls=[],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"output_file": "out.txt"},
        expected_output="out.txt",
    )

    assert result.ok is True


def test_model_routing_passes_resolved_profile_to_client_factory(
    tmp_path, monkeypatch
) -> None:
    recipe = write_recipe(tmp_path)
    init_git_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    config = load_config(
        {
            "TARGET_REPO": "atvirokodosprendimai/wgmesh",
            "DATABASE_MODE": "local",
            "MODEL_REGISTRY": (
                '{"capable": {"provider": "openrouter", "model": "anthropic/claude", '
                '"billing": "openrouter", "credential_env": "OPENROUTER_API_KEY", '
                '"host": "https://openrouter.ai/api/v1"}}'
            ),
            "STAGE_ROUTING": '{"implement": "capable"}',
            "OPENROUTER_API_KEY": "or-key",
        }
    )
    seen: list[ModelProfile] = []

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        seen.append(profile)
        return FakeClient(
            [
                FakeAIMessage(
                    content="writing",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "out.txt", "content": "done"},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                ),
                FakeAIMessage(content="finished", tool_calls=[], usage_metadata={}),
            ]
        )

    result = LangchainAgentRunner(config, client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={"spec_file": "spec.md"},
        expected_output="diff.patch",
        stage="implement",
    )

    assert result.ok is True
    assert seen[0].key == "capable"
    assert seen[0].model == "anthropic/claude"
    assert seen[0].host == "https://openrouter.ai/api/v1"
    assert result.model_key == "capable"


def test_missing_prompt_param_returns_not_ok(tmp_path) -> None:
    recipe = write_recipe(tmp_path)

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        raise AssertionError("client should not be constructed")

    result = LangchainAgentRunner(cfg(), client_factory=client_factory).run_recipe(
        recipe=recipe,
        workdir=tmp_path,
        params={},
        expected_output="out.txt",
    )

    assert result.ok is False
    assert "missing required recipe params: output_file" == result.error
