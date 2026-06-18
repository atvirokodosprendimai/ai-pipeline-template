from __future__ import annotations

import pytest

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
