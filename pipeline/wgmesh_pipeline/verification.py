from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("wgmesh_pipeline.verification")

DEFAULT_GO_BIN = Path("/usr/local/bin/go")
OUTPUT_TAIL_CHARS = 2000


def run_verification(
    repo_path: Path,
    branch: str,
    *,
    runner=subprocess.run,
    timeout: int = 600,
    go_bin: str | None = None,
) -> dict:
    go = _resolve_go(go_bin)
    if go is None:
        log.error("verification: go binary not found")
        return {
            "tests_passed": False,
            "steps": [],
            "failed_step": None,
            "output_tail": "",
            "reason": "go binary not found",
        }

    # The gate merges the REMOTE branch (the GitHub PR head), so verify that
    # exact state when it is reachable; a stale local branch must not vouch
    # for code it doesn't match. Local checkout is only a fallback for
    # remoteless test repos / network blips.
    fetch = _run(runner, ["git", "fetch", "origin", branch], repo_path, timeout)
    if fetch.returncode == 0:
        checkout = _run(runner, ["git", "checkout", "-B", branch, "FETCH_HEAD"], repo_path, timeout)
    else:
        checkout = _run(runner, ["git", "checkout", branch], repo_path, timeout)
    if checkout.returncode != 0:
        fallback = _run(runner, ["git", "checkout", branch], repo_path, timeout)
        if fallback.returncode != 0:
            stderr = fallback.stderr or checkout.stderr or ""
            reason = f"branch checkout failed: {stderr}"
            log.error("verification: %s", reason)
            return {
                "tests_passed": False,
                "steps": [],
                "failed_step": None,
                "output_tail": _tail((fallback.stdout or "") + stderr),
                "reason": reason,
            }

    steps: list[dict[str, Any]] = []
    started = time.monotonic()
    for name, args in (
        ("go build", [go, "build", "./..."]),
        ("go test", [go, "test", "./..."]),
        ("go vet", [go, "vet", "./..."]),
    ):
        step_started = time.monotonic()
        try:
            completed = _run(runner, args, repo_path, timeout)
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - step_started
            output = _timeout_output(exc)
            steps.append({"cmd": name, "returncode": -1, "duration_seconds": duration})
            _log_failure(name, output)
            return {
                "tests_passed": False,
                "steps": steps,
                "failed_step": name,
                "output_tail": _tail(output),
                "reason": "timeout",
            }
        duration = time.monotonic() - step_started
        steps.append({"cmd": name, "returncode": completed.returncode, "duration_seconds": duration})
        if completed.returncode != 0:
            output = (completed.stdout or "") + (completed.stderr or "")
            _log_failure(name, output)
            return {
                "tests_passed": False,
                "steps": steps,
                "failed_step": name,
                "output_tail": _tail(output),
                "reason": f"{name} failed",
            }

    total = time.monotonic() - started
    log.info("verification: go build/test/vet green on %s in %.2fs", branch, total)
    return {
        "tests_passed": True,
        "steps": steps,
        "failed_step": None,
        "output_tail": "",
    }


def _resolve_go(go_bin: str | None) -> str | None:
    if go_bin:
        return go_bin
    found = shutil.which("go")
    if found:
        return found
    if DEFAULT_GO_BIN.exists():
        return str(DEFAULT_GO_BIN)
    return None


def _run(runner, cmd: list[str], cwd: Path, timeout: int):
    return runner(
        cmd,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    output = _to_text(exc.output)
    stderr = _to_text(exc.stderr)
    return output + stderr


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _tail(output: str) -> str:
    return output[-OUTPUT_TAIL_CHARS:]


def _log_failure(step: str, output: str) -> None:
    head = output[:6000]
    tail = output[-OUTPUT_TAIL_CHARS:] if len(output) > 8000 else ""
    log.error(
        "verification failed at %s len(output)=%d\n"
        "--- verification output (head) ---\n%s\n--- verification output (tail) ---\n%s",
        step,
        len(output),
        head,
        tail,
    )
