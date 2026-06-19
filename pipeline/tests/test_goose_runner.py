from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.goose.runner import GooseRunner, _read_deliverable_safely
from wgmesh_pipeline.goose.usage import UsageTotals


def cfg() -> Config:
    return Config(
        target_repo="atvirokodosprendimai/wgmesh",
        zai_api_key="zai",
        anthropic_host="https://api.z.ai/api/anthropic",
    )


def completed(code: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["goose"], returncode=code, stdout=stdout, stderr=stderr)


def write_usage(logs: Path, *, input_tokens: int = 12, output_tokens: int = 7, total_tokens: int = 19) -> None:
    (logs / "llm_request.1.jsonl").write_text(
        (
            '{"usage":{'
            f'"input_tokens":{input_tokens},'
            f'"output_tokens":{output_tokens},'
            f'"total_tokens":{total_tokens}'
            "}}\n"
        ),
        encoding="utf-8",
    )


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


def test_goose_runner_populates_usage_and_emits_generation(tmp_path, monkeypatch) -> None:
    logs = tmp_path / "goose-logs"
    logs.mkdir()
    output = tmp_path / "specs/issue-19-spec.md"
    emitted: list[dict[str, Any]] = []

    monkeypatch.setattr("wgmesh_pipeline.goose.runner.default_logs_dir", lambda: logs)
    monkeypatch.setattr(
        "wgmesh_pipeline.goose.runner.tracing.emit_generation",
        lambda **kwargs: emitted.append(kwargs),
    )

    def run(command, **kwargs):
        output.parent.mkdir()
        output.write_text("content")
        write_usage(logs)
        return completed(stdout="wrote spec")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="recipe.yaml",
        workdir=tmp_path,
        params={},
        expected_output=output,
        stage="spec",
        session_id="issue-19",
    )

    assert result.ok is True
    assert result.usage == UsageTotals(input_tokens=12, output_tokens=7, total_tokens=19, requests=1, skipped=0)
    assert emitted == [
        {
            "session_id": "issue-19",
            "stage": "spec",
            "model": cfg().goose_model,
            "usage": result.usage,
            "output": "content",
        }
    ]


def test_goose_runner_failure_emits_usage_without_output(tmp_path, monkeypatch) -> None:
    logs = tmp_path / "goose-logs"
    logs.mkdir()
    emitted: list[dict[str, Any]] = []

    monkeypatch.setattr("wgmesh_pipeline.goose.runner.default_logs_dir", lambda: logs)
    monkeypatch.setattr(
        "wgmesh_pipeline.goose.runner.tracing.emit_generation",
        lambda **kwargs: emitted.append(kwargs),
    )

    def run(command, **kwargs):
        (logs / "llm_request.1.jsonl").write_text(
            '{"usage":{"input_tokens":5,"output_tokens":8,"total_tokens":13}}\n',
            encoding="utf-8",
        )
        return completed(2, stdout="partial", stderr="bad recipe")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-implementation.yaml",
        workdir=tmp_path,
        params={"spec_file": "spec.md"},
        expected_output="diff.patch",
        stage="implement",
        session_id="issue-20",
    )

    assert result.ok is False
    assert len(emitted) == 1
    assert emitted[0]["session_id"] == "issue-20"
    assert emitted[0]["stage"] == "implement"
    assert emitted[0]["model"] == cfg().goose_model
    assert emitted[0]["usage"] == result.usage
    assert emitted[0].get("output") is None


def test_goose_runner_success_emits_generation_once_with_deliverable_text(tmp_path, monkeypatch) -> None:
    logs = tmp_path / "goose-logs"
    logs.mkdir()
    output = tmp_path / "specs/issue-21-spec.md"
    deliverable = "## Deliverable\n\nConcrete stage text."
    emitted: list[dict[str, Any]] = []

    monkeypatch.setattr("wgmesh_pipeline.goose.runner.default_logs_dir", lambda: logs)
    monkeypatch.setattr(
        "wgmesh_pipeline.goose.runner.tracing.emit_generation",
        lambda **kwargs: emitted.append(kwargs),
    )

    def run(command, **kwargs):
        output.parent.mkdir()
        output.write_text(deliverable, encoding="utf-8")
        write_usage(logs)
        return completed(stdout="wrote spec")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="recipe.yaml",
        workdir=tmp_path,
        params={},
        expected_output=output,
        stage="spec",
        session_id="issue-21",
    )

    assert result.ok is True
    assert len(emitted) == 1
    assert emitted[0]["usage"] == result.usage
    assert emitted[0]["output"] == deliverable


def test_goose_runner_nonzero_emits_usage_once_without_deliverable(tmp_path, monkeypatch) -> None:
    logs = tmp_path / "goose-logs"
    logs.mkdir()
    emitted: list[dict[str, Any]] = []

    monkeypatch.setattr("wgmesh_pipeline.goose.runner.default_logs_dir", lambda: logs)
    monkeypatch.setattr(
        "wgmesh_pipeline.goose.runner.tracing.emit_generation",
        lambda **kwargs: emitted.append(kwargs),
    )

    def run(command, **kwargs):
        write_usage(logs)
        return completed(2, stdout="partial", stderr="bad recipe")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-implementation.yaml",
        workdir=tmp_path,
        params={"spec_file": "spec.md"},
        expected_output="diff.patch",
        stage="implement",
        session_id="issue-22",
    )

    assert result.ok is False
    assert len(emitted) == 1
    assert emitted[0]["usage"] == result.usage
    assert emitted[0].get("output") is None


def test_goose_runner_salvage_write_failure_emits_usage_once_without_deliverable(
    tmp_path, monkeypatch
) -> None:
    logs = tmp_path / "goose-logs"
    logs.mkdir()
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    emitted: list[dict[str, Any]] = []

    monkeypatch.setattr("wgmesh_pipeline.goose.runner.default_logs_dir", lambda: logs)
    monkeypatch.setattr(
        "wgmesh_pipeline.goose.runner.tracing.emit_generation",
        lambda **kwargs: emitted.append(kwargs),
    )

    def run(command, **kwargs):
        write_usage(logs)
        return completed(0, stdout="# Spec\n\n" + ("body\n" * 80))

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-triage-spec.yaml",
        workdir=tmp_path,
        params={"spec_file": "blocked/out.md"},
        expected_output="blocked/out.md",
        stage="spec",
        session_id="issue-23",
    )

    assert result.ok is False
    assert "salvage write failed" in (result.error or "")
    assert len(emitted) == 1
    assert emitted[0]["usage"] == result.usage
    assert emitted[0].get("output") is None


def test_goose_runner_empty_output_guard_emits_usage_once_without_deliverable(
    tmp_path, monkeypatch
) -> None:
    logs = tmp_path / "goose-logs"
    logs.mkdir()
    emitted: list[dict[str, Any]] = []

    monkeypatch.setattr("wgmesh_pipeline.goose.runner.default_logs_dir", lambda: logs)
    monkeypatch.setattr(
        "wgmesh_pipeline.goose.runner.tracing.emit_generation",
        lambda **kwargs: emitted.append(kwargs),
    )

    def run(command, **kwargs):
        write_usage(logs)
        return completed(0, stdout="done, no file written")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="wgmesh-triage-spec.yaml",
        workdir=tmp_path,
        params={"spec_file": "specs/issue-24-spec.md"},
        expected_output="specs/issue-24-spec.md",
        stage="spec",
        session_id="issue-24",
    )

    assert result.ok is False
    assert "empty output guard" in (result.error or "")
    assert len(emitted) == 1
    assert emitted[0]["usage"] == result.usage
    assert emitted[0].get("output") is None


def test_read_deliverable_safely_reads_and_truncates(tmp_path) -> None:
    output = tmp_path / "out.txt"
    output.write_text("abcdef", encoding="utf-8")

    assert _read_deliverable_safely(output, limit=4) == "abcd"


def test_read_deliverable_safely_returns_none_on_oserror(tmp_path) -> None:
    missing = tmp_path / "missing.txt"

    assert _read_deliverable_safely(missing) is None


def test_goose_runner_usage_collection_exception_does_not_break_run(tmp_path, monkeypatch) -> None:
    output = tmp_path / "specs/issue-20-spec.md"
    emitted: list[dict[str, Any]] = []

    def boom():
        raise OSError("logs unavailable")

    monkeypatch.setattr("wgmesh_pipeline.goose.runner.default_logs_dir", boom)
    monkeypatch.setattr(
        "wgmesh_pipeline.goose.runner.tracing.emit_generation",
        lambda **kwargs: emitted.append(kwargs),
    )

    def run(command, **kwargs):
        output.parent.mkdir()
        output.write_text("content")
        return completed(stdout="wrote spec")

    result = GooseRunner(cfg(), runner=run).run_recipe(
        recipe="recipe.yaml",
        workdir=tmp_path,
        params={},
        expected_output=output,
        stage="spec",
        session_id="issue-20",
    )

    assert result.ok is True
    assert result.usage is None
    assert emitted == []
