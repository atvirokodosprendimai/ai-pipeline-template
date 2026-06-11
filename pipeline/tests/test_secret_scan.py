from __future__ import annotations

import subprocess
from pathlib import Path

from wgmesh_pipeline.secret_scan import scan_diff_for_secrets


def test_found_true_when_json_has_incidents() -> None:
    def runner(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=(
                '{"entities_with_incidents": ['
                '{"incidents": [{"type": "HardcodedPassword"}]}'
                "]}"
            ),
            stderr="",
        )

    result = scan_diff_for_secrets("+password = 'abc'\n", runner=runner, ggshield_bin="ggshield")

    assert result.available is True
    assert result.found is True
    assert result.detail == "ggshield: 1 incident(s) [HardcodedPassword]"


def test_found_false_when_json_has_empty_entities() -> None:
    def runner(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout='{"entities_with_incidents": []}',
            stderr="",
        )

    result = scan_diff_for_secrets("+testSecret flag\n", runner=runner, ggshield_bin="ggshield")

    assert result.available is True
    assert result.found is False
    assert result.detail == "ggshield: 0 incident(s)"


def test_available_false_when_binary_missing(monkeypatch) -> None:
    monkeypatch.setattr("wgmesh_pipeline.secret_scan.shutil.which", lambda name: None)

    result = scan_diff_for_secrets("+SECRET_KEY=abc\n", ggshield_bin=None)

    assert result.available is False
    assert result.found is False
    assert result.detail == "ggshield not installed"


def test_available_false_on_unparseable_stdout_and_nonzero_returncode() -> None:
    def runner(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="authentication required",
            stderr="missing GITGUARDIAN_API_KEY",
        )

    result = scan_diff_for_secrets("+secret\n", runner=runner, ggshield_bin="ggshield")

    assert result.available is False
    assert result.found is False
    assert result.detail == "ggshield invalid json"


def test_timeout_path() -> None:
    def runner(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    result = scan_diff_for_secrets("+secret\n", runner=runner, ggshield_bin="ggshield")

    assert result.available is False
    assert result.found is False
    assert result.detail == "ggshield timeout"


def test_temp_file_is_removed_after_call() -> None:
    temp_paths: list[str] = []

    def runner(args, **kwargs) -> subprocess.CompletedProcess[str]:
        temp_paths.append(args[4])
        assert Path(args[4]).exists()
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout='{"entities_with_incidents": []}',
            stderr="",
        )

    result = scan_diff_for_secrets("+small\n", runner=runner, ggshield_bin="ggshield")

    assert result.available is True
    assert temp_paths
    assert not Path(temp_paths[0]).exists()
