"""Control-loop action executor tests (U2).

Pins the single-write-path contract: every one of the 12 planner action kinds
maps to the right forge method with the right (sanitised) content; a sanitise
failure blocks ONLY that action; an unknown kind is a loud skip; one action
raising never aborts the batch; and a shadow-configured real forge routes
through the executor producing dry-runs with zero HTTP writes.

Frozen fixtures only (PR #1691): real HealAction / ObservationAction values, a
recording forge that stubs at the method boundary WITHOUT overriding any gate,
and (for the sanitise + shadow proofs) a real GitHubClient with the HTTP
session stubbed — the lowest boundary, so the sanitise/write gates stay in the
execution path (test-fakes-override-the-gate lesson).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.control_loop.executor import (
    BLOCKED,
    ERROR,
    EXECUTED,
    SKIPPED,
    execute_action,
    execute_actions,
)
from wgmesh_pipeline.github.client import DryRunResult, GitHubClient
from wgmesh_pipeline.observation import ObservationAction
from wgmesh_pipeline.selfheal.models import HealAction


# --- recording forge (method-boundary stub; gates not overridden) -----------


class RecordingForge:
    """Records each forge method call as (name, args, kwargs). Returns a marker
    so the executor's EXECUTED path is exercised. Does NOT model gates — the
    gate-bearing proofs use a real GitHubClient below."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str):
        def method(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            return {"ok": name}

        return method

    def __getattr__(self, name: str):
        return self._record(name)

    @property
    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


def _github(mode: str, sanitiser=lambda _t: True) -> tuple[GitHubClient, "RoutingSession"]:
    cfg = Config(target_repo="o/r", mode=mode, wgmesh_bot_pat="pat")
    session = RoutingSession()
    return GitHubClient(cfg, session=session, sanitiser=sanitiser), session


class RoutingSession:
    """Records HTTP requests; every call succeeds with an empty body. Used to
    prove shadow performs ZERO HTTP and live performs the expected writes."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})

        class _Resp:
            text = ""

            def raise_for_status(self) -> None:
                return None

            def json(self) -> Any:
                return {}

        return _Resp()


# --- dispatch: each kind -> right forge method ------------------------------


def test_create_issue_routes_to_create_issue() -> None:
    forge = RecordingForge()
    action = ObservationAction(
        kind="create_issue", title="t", body="b", labels=("bug",)
    )
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.names == ["create_issue"]
    assert forge.calls[0][2] == {"title": "t", "body": "b", "labels": ("bug",)}


def test_create_needs_human_routes_to_create_issue_with_label() -> None:
    forge = RecordingForge()
    action = ObservationAction(
        kind="create_needs_human", title="[needs-human] x", body="b",
        labels=("needs-human",),
    )
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.calls[0] == ("create_issue", (), {"title": "[needs-human] x", "body": "b", "labels": ("needs-human",)})


@pytest.mark.parametrize("kind", ["supervisor_dead", "circuit_breaker"])
def test_repo_level_escalation_kinds_create_needs_human_issue(kind: str) -> None:
    forge = RecordingForge()
    action = HealAction(kind=kind, target="issue", title="dead", body="why", add_label="needs-human")
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.names == ["create_issue"]
    assert forge.calls[0][2]["labels"] == ("needs-human",)


def test_escalate_existing_issue_comments_then_labels() -> None:
    forge = RecordingForge()
    action = HealAction(kind="escalate", number=42, body="exceeded retries", add_label="needs-human")
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.names == ["comment", "add_label"]
    assert forge.calls[0][1] == (42, "exceeded retries")
    assert forge.calls[1][1] == (42, "needs-human")


def test_escalate_without_number_creates_issue() -> None:
    forge = RecordingForge()
    action = HealAction(kind="escalate", number=None, title="t", body="b", add_label="needs-human")
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.names == ["create_issue"]


def test_close_issue_routes_with_comment_and_state_reason() -> None:
    forge = RecordingForge()
    action = ObservationAction(
        kind="close_issue", number=7, close_reason="not planned",
        comment="Closed by observation loop: done", reason="done",
    )
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.names == ["close_issue"]
    name, args, kwargs = forge.calls[0]
    assert args[0] == 7
    assert args[1] == "Closed by observation loop: done"
    assert kwargs == {"state_reason": "not planned"}


def test_close_needs_human_routes_to_close_issue() -> None:
    forge = RecordingForge()
    action = HealAction(kind="close_needs_human", number=9, comment="Resolved by self-healing: X")
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.names == ["close_issue"]
    assert forge.calls[0][1] == (9, "Resolved by self-healing: X")


def test_close_pr_routes_to_close_pr() -> None:
    forge = RecordingForge()
    action = ObservationAction(kind="close_pr", number=8, comment="superseded")
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.names == ["close_pr"]
    assert forge.calls[0][1] == (8, "superseded")


@pytest.mark.parametrize(
    "kind,remove,add",
    [
        ("retrigger_triage", "needs-triage", "needs-triage"),
        ("retrigger_copilot", "copilot-triaging", "needs-triage"),
        ("retrigger_goose", "approved-for-build", "approved-for-build"),
    ],
)
def test_retrigger_kinds_toggle_labels(kind: str, remove: str, add: str) -> None:
    forge = RecordingForge()
    action = HealAction(kind=kind, number=5, remove_label=remove, add_label=add)
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.names == ["remove_label", "add_label"]
    assert forge.calls[0][1] == (5, remove)
    assert forge.calls[1][1] == (5, add)


def test_dispatch_observation_loop_routes_to_dispatch_workflow() -> None:
    forge = RecordingForge()
    action = HealAction(
        kind="dispatch_observation_loop", target="repo",
        body="signal=idle-pipeline", reason="idle pipeline",
    )
    result = execute_action(forge, None, action)
    assert result.status == EXECUTED
    assert forge.names == ["dispatch_workflow"]
    workflow, inputs = forge.calls[0][1]
    assert workflow == "observation-loop.yml"
    assert inputs["signal"] == "signal=idle-pipeline"


# --- safety posture ---------------------------------------------------------


def test_unknown_kind_is_loud_skip(caplog) -> None:
    forge = RecordingForge()

    class Bogus:
        kind = "teleport_issue"

    with caplog.at_level(logging.WARNING, logger="wgmesh_pipeline.control_loop.executor"):
        result = execute_action(forge, None, Bogus())
    assert result.status == SKIPPED
    assert forge.calls == []
    assert "unknown action kind" in caplog.text


def test_sanitise_failure_blocks_only_that_action(caplog) -> None:
    # Real GitHubClient with a sanitiser that always fails: create_issue's
    # title/body emit hits the gate inside _write and raises SanitiseError,
    # which the executor converts to a BLOCKED result (no crash, no HTTP).
    client, session = _github("live", sanitiser=lambda _t: False)
    action = ObservationAction(kind="create_issue", title="leak", body="secret")
    with caplog.at_level(logging.WARNING, logger="wgmesh_pipeline.control_loop.executor"):
        result = execute_action(client, None, action)
    assert result.status == BLOCKED
    assert session.calls == []  # gate fired BEFORE any HTTP write
    assert "sanitise gate BLOCKED" in caplog.text


def test_forge_exception_becomes_error_result_not_crash(caplog) -> None:
    class Boom:
        def create_issue(self, **kwargs: Any) -> Any:
            raise RuntimeError("422 already exists")

        def __getattr__(self, name: str):
            def m(*a: Any, **k: Any) -> Any:
                raise RuntimeError("boom")

            return m

    action = ObservationAction(kind="create_issue", title="t", body="b")
    with caplog.at_level(logging.ERROR, logger="wgmesh_pipeline.control_loop.executor"):
        result = execute_action(Boom(), None, action)
    assert result.status == ERROR
    assert "422 already exists" in result.detail


def test_one_action_raising_does_not_abort_the_batch() -> None:
    # First action errors (forge raises), second succeeds — both results return.
    class HalfBroken:
        def __init__(self) -> None:
            self.created = 0

        def close_pr(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("PR already closed")

        def create_issue(self, **kwargs: Any) -> Any:
            self.created += 1
            return {"number": 1}

    forge = HalfBroken()
    actions = [
        ObservationAction(kind="close_pr", number=8, comment="x"),
        ObservationAction(kind="create_issue", title="t", body="b"),
    ]
    results = execute_actions(forge, None, actions)
    assert [r.status for r in results] == [ERROR, EXECUTED]
    assert forge.created == 1  # the second action still ran


# --- shadow routing: through the executor, zero real writes -----------------


def test_shadow_routes_through_executor_with_zero_http_writes() -> None:
    # The U2 cardinal proof: a shadow-configured REAL forge routed through the
    # executor produces DryRunResults and performs ZERO HTTP. The path runs;
    # nothing is written.
    client, session = _github("shadow")
    actions = [
        ObservationAction(kind="create_issue", title="t", body="b", labels=("bug",)),
        ObservationAction(kind="close_pr", number=8, comment="superseded"),
        HealAction(kind="retrigger_triage", number=5, remove_label="needs-triage", add_label="needs-triage"),
    ]
    results = execute_actions(client, None, actions)
    assert [r.status for r in results] == [EXECUTED, EXECUTED, EXECUTED]
    assert session.calls == [], "shadow must perform zero HTTP writes"
    # Every emit produced a dry-run record (create_issue; close_pr -> comment +
    # state PATCH; retrigger -> two label writes).
    assert all(isinstance(r, DryRunResult) for r in client.dry_run_records)
    assert "create_issue" in [r.operation for r in client.dry_run_records]


def test_live_routes_through_executor_and_writes() -> None:
    client, session = _github("live")
    action = ObservationAction(kind="create_issue", title="t", body="b")
    result = execute_action(client, None, action)
    assert result.status == EXECUTED
    posts = [c for c in session.calls if c["method"] == "POST" and "/issues" in c["url"]]
    assert len(posts) == 1
