from __future__ import annotations

import subprocess
import types
from typing import Any

from wgmesh_pipeline.graph.nodes.guards import guards_node


class FakeClient:
    def __init__(self, pr: dict[str, Any]) -> None:
        self._pr = pr
        self.statuses: list[dict[str, Any]] = []

    def get_pr(self, number: int) -> dict[str, Any]:
        return self._pr

    def create_commit_status(
        self, sha: str, *, context: str, state: str, description: str = "", target_url=None
    ) -> None:
        self.statuses.append(
            {"sha": sha, "context": context, "state": state, "description": description}
        )


PR = {"base": {"sha": "base000"}, "head": {"sha": "head111"}}


def make_runner(*, pii_rc: int = 0, emit_rc: int = 0, raise_on: str | None = None):
    def runner(cmd: list[str], **kwargs: Any):
        script = cmd[1]
        if raise_on and raise_on in script:
            raise subprocess.TimeoutExpired(cmd, 1)
        rc = pii_rc if "check-pii-policy" in script else emit_rc
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="")

    return runner


def base_state(client: FakeClient, **over: Any) -> dict[str, Any]:
    state = {
        "repo_path": ".",
        "github": client,
        "goose_runner": object(),  # live-path sentinel (mirrors review_node)
        "impl_pr": 5,
        "tests_passed": True,
        "sanitise_ok": True,
    }
    state.update(over)
    return state


def test_synthetic_path_skips_guards_and_passes() -> None:
    # No goose_runner -> synthetic/shadow path: guards pass without running the
    # subprocess scans or posting a status (mirrors review_node's fallback).
    client = FakeClient(PR)
    out = guards_node(
        {"repo_path": ".", "github": client, "impl_pr": 5}, runner=make_runner(pii_rc=1)
    )

    assert out["pii_ok"] is True
    assert out["emit_sanitise_ok"] is True
    assert client.statuses == []


def test_clean_guards_post_success() -> None:
    client = FakeClient(PR)
    out = guards_node(base_state(client), runner=make_runner())

    assert out["pii_ok"] is True
    assert out["emit_sanitise_ok"] is True
    status = client.statuses[-1]
    assert status["state"] == "success"
    assert status["context"] == "ci/guards"
    assert status["sha"] == "head111"


def test_pii_failure_blocks_and_posts_failure() -> None:
    client = FakeClient(PR)
    out = guards_node(base_state(client), runner=make_runner(pii_rc=1))

    assert out["pii_ok"] is False
    assert client.statuses[-1]["state"] == "failure"
    assert "pii" in client.statuses[-1]["description"]


def test_emit_sanitise_failure_blocks() -> None:
    client = FakeClient(PR)
    out = guards_node(base_state(client), runner=make_runner(emit_rc=1))

    assert out["emit_sanitise_ok"] is False
    assert client.statuses[-1]["state"] == "failure"
    assert "emit-sanitise" in client.statuses[-1]["description"]


def test_guard_timeout_fails_closed() -> None:
    client = FakeClient(PR)
    out = guards_node(base_state(client), runner=make_runner(raise_on="check-pii-policy"))

    assert out["pii_ok"] is False
    assert client.statuses[-1]["state"] == "failure"


def test_missing_head_sha_fails_pii_closed_and_skips_post() -> None:
    client = FakeClient({"base": {}, "head": {}})
    out = guards_node(base_state(client), runner=make_runner())

    assert out["pii_ok"] is False
    assert client.statuses == []  # no head sha -> no status posted


def test_status_description_never_contains_email() -> None:
    client = FakeClient(PR)
    guards_node(base_state(client), runner=make_runner(pii_rc=1))

    assert "@" not in client.statuses[-1]["description"]


def test_upstream_tests_failed_yields_failure_status() -> None:
    client = FakeClient(PR)
    out = guards_node(base_state(client, tests_passed=False), runner=make_runner())

    assert out["pii_ok"] is True  # the guards themselves are green
    assert client.statuses[-1]["state"] == "failure"  # aggregate includes tests
    assert "tests" in client.statuses[-1]["description"]


def test_status_post_error_does_not_crash() -> None:
    class BoomClient(FakeClient):
        def create_commit_status(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("boom")

    client = BoomClient(PR)
    out = guards_node(base_state(client), runner=make_runner())

    assert out["pii_ok"] is True  # the node still returns; the post error is swallowed
