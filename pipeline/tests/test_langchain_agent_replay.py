from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.langchain_agent import replay
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

    def bind_tools(self, specs: list[object]) -> FakeClient:
        return self

    def invoke(self, messages: list[Any]) -> FakeAIMessage:
        if len(self._messages) == 1:
            return self._messages[0]
        return self._messages.pop(0)


def cfg() -> Config:
    return Config(
        target_repo="atvirokodosprendimai/wgmesh",
        zai_api_key="zai",
        anthropic_host="https://api.z.ai/api/anthropic",
    )


def init_git_repo(tmp_path: Path) -> Path:
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
    spec = tmp_path / "spec.md"
    spec.write_text("Implement the change.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return spec


def test_replay_reports_ok_and_exits_zero_when_agent_edits_file(tmp_path: Path) -> None:
    spec = init_git_repo(tmp_path)
    stdout = io.StringIO()

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        return FakeClient(
            [
                FakeAIMessage(
                    content="editing",
                    tool_calls=[
                        {
                            "name": "edit_file",
                            "args": {
                                "path": "README.md",
                                "old": "initial\n",
                                "new": "implemented\n",
                            },
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

    code = replay.main(
        ["--spec", str(spec), "--workdir", str(tmp_path)],
        client_factory=client_factory,
        config_loader=cfg,
        stdout=stdout,
    )

    assert code == 0
    report = stdout.getvalue()
    assert "REPORT" in report
    assert "ok: True" in report
    assert "git_dirty: True" in report
    assert "README.md" in report
    assert "input_tokens=14" in report


def test_replay_exits_one_when_agent_makes_no_edits(tmp_path: Path) -> None:
    spec = init_git_repo(tmp_path)
    stdout = io.StringIO()

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

    code = replay.main(
        ["--spec", str(spec), "--workdir", str(tmp_path)],
        client_factory=client_factory,
        config_loader=cfg,
        stdout=stdout,
    )

    assert code == 1
    report = stdout.getvalue()
    assert "ok: False" in report
    assert "git_dirty: False" in report
    assert "no source changes" in report


def test_replay_model_override_sets_goose_model_before_running(
    tmp_path: Path,
) -> None:
    spec = init_git_repo(tmp_path)
    stdout = io.StringIO()
    seen_models: list[str] = []

    def client_factory(profile: ModelProfile, config: Config) -> FakeClient:
        seen_models.append(profile.model)
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

    code = replay.main(
        ["--spec", str(spec), "--workdir", str(tmp_path), "--model", "X"],
        client_factory=client_factory,
        config_loader=cfg,
        stdout=stdout,
    )

    assert code == 0
    assert seen_models == ["X"]
    assert "model: X" in stdout.getvalue()
