from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.goose.runner import GooseRunner


def cfg() -> Config:
    return Config(
        target_repo="atvirokodosprendimai/wgmesh",
        zai_api_key="zai",
        anthropic_host="https://api.z.ai/api/anthropic",
    )


def completed(code: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["goose"], returncode=code, stdout=stdout, stderr=stderr)


def test_mocked_goose_writes_spec_file_and_returns_ok(tmp_path) -> None:
    calls: list[dict[str, Any]] = []

    def run(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        output = Path(kwargs["cwd"]) / "specs/issue-17-spec.md"
        output.parent.mkdir(parents=True)
        output.write_text("## Problem\n\n## Proposed Approach\n\n## Acceptance Criteria\n")
        return completed(stdout="wrote spec")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-triage-spec.yaml",
        workdir=tmp_path,
        params={"spec_file": "specs/issue-17-spec.md"},
        expected_output="specs/issue-17-spec.md",
    )

    assert result.ok is True
    assert result.output_path == tmp_path / "specs/issue-17-spec.md"
    assert "wrote spec" in result.raw_log
    assert calls[0]["command"][:5] == ["goose", "run", "--no-session", "--recipe", "wgmesh-triage-spec.yaml"]
    assert "ANTHROPIC_API_KEY" in calls[0]["kwargs"]["env"]


def test_goose_nonzero_returns_not_ok_with_raw_log(tmp_path) -> None:
    def run(command, **kwargs):
        return completed(2, stdout="partial", stderr="bad recipe")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-implementation.yaml",
        workdir=tmp_path,
        params={"spec_file": "spec.md"},
        expected_output="diff.patch",
    )

    assert result.ok is False
    assert result.error == "goose exited 2"
    assert "partial" in result.raw_log
    assert "bad recipe" in result.raw_log


def test_goose_timeout_returns_not_ok_without_propagating(tmp_path) -> None:
    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs["timeout"])

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-implementation.yaml",
        workdir=tmp_path,
        params={"spec_file": "spec.md"},
        expected_output="diff.patch",
    )

    assert result.ok is False
    assert result.error == "goose timed out after 1800s"


def test_goose_zero_exit_empty_output_fails_loudly(tmp_path) -> None:
    def run(command, **kwargs):
        return completed(0, stdout="done but no file")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-triage-spec.yaml",
        workdir=tmp_path,
        params={"spec_file": "specs/issue-17-spec.md"},
        expected_output="specs/issue-17-spec.md",
    )

    assert result.ok is False
    assert result.error is not None
    assert "empty output guard" in result.error


def test_printed_only_spec_is_salvaged_from_stdout(tmp_path) -> None:
    # glm-4.6 often PRINTS the spec instead of calling the developer write tool.
    # goose exits 0, stdout carries the markdown, file is never written. The
    # runner must salvage stdout to the expected path rather than fail.
    spec_text = "# Summary\n\n" + ("Concrete spec body line.\n" * 40)
    assert len(spec_text) >= 200

    def run(command, **kwargs):
        # Note: does NOT write the file — model printed instead.
        return completed(0, stdout="\x1b[32m" + spec_text + "\x1b[0m")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-triage-spec.yaml",
        workdir=tmp_path,
        params={"spec_file": "specs/issue-651-spec.md"},
        expected_output="specs/issue-651-spec.md",
    )

    assert result.ok is True
    written = tmp_path / "specs/issue-651-spec.md"
    assert written.exists()
    body = written.read_text()
    assert "# Summary" in body
    assert "\x1b[" not in body  # ANSI stripped


def test_trivial_stdout_still_fails_guard_no_junk_salvage(tmp_path) -> None:
    # A short acknowledgement line is NOT a spec — must not be salvaged.
    def run(command, **kwargs):
        return completed(0, stdout="done, no file written")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-triage-spec.yaml",
        workdir=tmp_path,
        params={"spec_file": "specs/issue-17-spec.md"},
        expected_output="specs/issue-17-spec.md",
    )

    assert result.ok is False
    assert "empty output guard" in (result.error or "")
    assert not (tmp_path / "specs/issue-17-spec.md").exists()


def test_near_zero_duration_is_surfaced(tmp_path, monkeypatch) -> None:
    output = tmp_path / "specs/issue-18-spec.md"
    times = iter([10.0, 10.0001])
    monkeypatch.setattr("wgmesh_pipeline.goose.runner.time.monotonic", lambda: next(times))

    def run(command, **kwargs):
        output.parent.mkdir()
        output.write_text("content")
        return completed()

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="recipe.yaml",
        workdir=tmp_path,
        params={"spec_file": "specs/issue-18-spec.md"},
        expected_output=output,
    )

    assert result.ok is True
    assert 0 < result.duration_seconds < 0.001
