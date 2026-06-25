from __future__ import annotations

import subprocess

import pytest

from wgmesh_pipeline.langchain_agent import tools as tools_mod
from wgmesh_pipeline.langchain_agent.tools import build_tools

pytestmark = pytest.mark.unit


def test_path_escape_attempt_is_rejected(tmp_path) -> None:
    _, dispatch = build_tools(tmp_path)

    with pytest.raises(ValueError, match="escapes workspace"):
        dispatch["write_file"]("../outside.txt", "nope")


def test_write_file_then_read_file_round_trips(tmp_path) -> None:
    _, dispatch = build_tools(tmp_path)

    assert "wrote" in dispatch["write_file"]("nested/out.txt", "hello")

    assert dispatch["read_file"]("nested/out.txt") == "hello"


def test_run_bash_captures_exit_stdout_and_stderr(tmp_path) -> None:
    _, dispatch = build_tools(tmp_path)

    result = dispatch["run_bash"]("printf ok && printf err >&2 && exit 7")

    assert "exit=7" in result
    assert "stdout:\nok" in result
    assert "stderr:\nerr" in result


def _record_subprocess(monkeypatch):
    """Patch subprocess.run in the tools module to capture its call and return a
    benign CompletedProcess, so no real bash/bwrap executes."""
    calls: list[dict] = []

    def fake_run(args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(tools_mod.subprocess, "run", fake_run)
    return calls


def test_run_bash_wraps_in_bwrap_when_available(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tools_mod.shutil, "which", lambda name: "/usr/bin/bwrap")
    calls = _record_subprocess(monkeypatch)

    _, dispatch = build_tools(tmp_path)
    dispatch["run_bash"]("go build ./...")

    argv = calls[0]["args"]
    root = str(tmp_path.resolve())
    cache = tools_mod.AGENT_CACHE_DIR
    assert argv[0] == "bwrap"

    # Both the workspace and the cache dir are re-bound writable, each as an
    # adjacent `--bind <path> <path>` triple after the read-only root bind.
    def _has_writable_bind(path: str) -> bool:
        return any(
            argv[i] == "--bind" and argv[i + 1] == path and argv[i + 2] == path
            for i in range(len(argv) - 2)
        )

    assert _has_writable_bind(root)
    assert _has_writable_bind(cache)
    assert "--die-with-parent" in argv
    # network is kept for go mod / pip egress
    assert "--unshare-net" not in argv
    # not invoked through the shell when sandboxed
    assert calls[0]["kwargs"].get("shell") is not True

    # Toolchains point at subdirs of the writable cache (host root is read-only).
    env = calls[0]["kwargs"]["env"]
    assert env["GOMODCACHE"] == f"{cache}/gomod"
    assert env["GOCACHE"] == f"{cache}/gocache"
    assert env["GOPATH"] == f"{cache}/go"
    assert env["PIP_CACHE_DIR"] == f"{cache}/pip"
    assert env["XDG_CACHE_HOME"] == f"{cache}/xdg"
    assert env["HOME"] == f"{cache}/home"
    # GOFLAGS=-modcacherw from _safe_subprocess_env is preserved
    assert "-modcacherw" in env["GOFLAGS"]


def test_run_bash_falls_back_to_bare_command_without_bwrap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tools_mod.shutil, "which", lambda name: None)
    calls = _record_subprocess(monkeypatch)

    _, dispatch = build_tools(tmp_path)
    dispatch["run_bash"]("echo hi")

    assert calls[0]["args"] == "echo hi"
    assert calls[0]["kwargs"].get("shell") is True
