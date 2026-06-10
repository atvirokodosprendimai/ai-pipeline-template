from __future__ import annotations

import subprocess
from pathlib import Path

from wgmesh_pipeline import verification
from wgmesh_pipeline.verification import run_verification


class FakeRunner:
    def __init__(self, failures: dict[tuple[str, ...], subprocess.CompletedProcess[str]] | None = None):
        self.failures = failures or {}
        self.commands: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        command = [str(part) for part in cmd]
        self.commands.append(command)
        key = tuple(command)
        if key in self.failures:
            return self.failures[key]
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


def test_run_verification_success_runs_go_steps_in_order(tmp_path: Path) -> None:
    runner = FakeRunner()

    result = run_verification(tmp_path, "bot/impl-7", runner=runner, go_bin="/bin/go")

    assert result["tests_passed"] is True
    assert result["failed_step"] is None
    assert result["output_tail"] == ""
    assert [step["cmd"] for step in result["steps"]] == ["go build", "go test", "go vet"]
    assert runner.commands[-3:] == [
        ["/bin/go", "build", "./..."],
        ["/bin/go", "test", "./..."],
        ["/bin/go", "vet", "./..."],
    ]


def test_run_verification_stops_on_go_test_failure_and_captures_tail(tmp_path: Path) -> None:
    failure = subprocess.CompletedProcess(
        ["/bin/go", "test", "./..."],
        1,
        stdout="test stdout\n",
        stderr="test stderr\n",
    )
    runner = FakeRunner({("/bin/go", "test", "./..."): failure})

    result = run_verification(tmp_path, "bot/impl-7", runner=runner, go_bin="/bin/go")

    assert result["tests_passed"] is False
    assert result["failed_step"] == "go test"
    assert "test stdout" in result["output_tail"]
    assert "test stderr" in result["output_tail"]
    assert [step["cmd"] for step in result["steps"]] == ["go build", "go test"]
    assert ["/bin/go", "vet", "./..."] not in runner.commands


def test_run_verification_checkout_failure_returns_reason(tmp_path: Path) -> None:
    failures = {
        ("git", "checkout", "bot/impl-7"): subprocess.CompletedProcess(
            ["git", "checkout", "bot/impl-7"],
            1,
            stdout="",
            stderr="local missing",
        ),
        ("git", "checkout", "-B", "bot/impl-7", "origin/bot/impl-7"): subprocess.CompletedProcess(
            ["git", "checkout", "-B", "bot/impl-7", "origin/bot/impl-7"],
            1,
            stdout="",
            stderr="remote missing",
        ),
    }
    runner = FakeRunner(failures)

    result = run_verification(tmp_path, "bot/impl-7", runner=runner, go_bin="/bin/go")

    assert result["tests_passed"] is False
    assert "branch checkout failed" in result["reason"]
    assert "remote missing" in result["reason"]


def test_run_verification_missing_go_binary_returns_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(verification.shutil, "which", lambda name: None)
    monkeypatch.setattr(verification, "DEFAULT_GO_BIN", tmp_path / "missing-go")

    result = run_verification(tmp_path, "bot/impl-7", runner=FakeRunner(), go_bin=None)

    assert result["tests_passed"] is False
    assert result["reason"] == "go binary not found"


def test_run_verification_timeout_records_failed_step(tmp_path: Path) -> None:
    class TimeoutRunner(FakeRunner):
        def __call__(self, cmd, **kwargs):
            command = [str(part) for part in cmd]
            self.commands.append(command)
            if command == ["/bin/go", "test", "./..."]:
                raise subprocess.TimeoutExpired(command, timeout=600, output="partial", stderr="slow")
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = run_verification(tmp_path, "bot/impl-7", runner=TimeoutRunner(), go_bin="/bin/go")

    assert result["tests_passed"] is False
    assert result["failed_step"] == "go test"
    assert result["reason"] == "timeout"
    assert [step["cmd"] for step in result["steps"]] == ["go build", "go test"]
