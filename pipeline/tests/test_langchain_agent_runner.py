from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.config import Config, load_config
from wgmesh_pipeline.goose.usage import UsageTotals
from wgmesh_pipeline.langchain_agent.runner import LangchainAgentRunner
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

    def bind_tools(self, specs):
        self.bound_specs = list(specs)
        return self

    def invoke(self, messages):
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
        stage="implement",
    )

    assert result.ok is True
    assert result.output_path == tmp_path / "out.txt"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "done"
    assert result.usage == UsageTotals(
        input_tokens=14, output_tokens=5, total_tokens=19, requests=2, skipped=0
    )
    assert result.model_key == "default"


def test_emit_generation_called_with_stage_model_and_usage(
    tmp_path, monkeypatch
) -> None:
    recipe = write_recipe(tmp_path)
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
        params={"output_file": "out.txt"},
        expected_output="out.txt",
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


def test_max_iterations_is_bounded(tmp_path) -> None:
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
    assert "max iterations" in (result.error or "")
    assert result.usage is not None
    assert result.usage.requests == 25


def test_model_routing_passes_resolved_profile_to_client_factory(
    tmp_path, monkeypatch
) -> None:
    recipe = write_recipe(tmp_path)
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
        params={"output_file": "out.txt"},
        expected_output="out.txt",
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
