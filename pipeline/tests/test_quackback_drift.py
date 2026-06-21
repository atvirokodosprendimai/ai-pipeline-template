"""U12 — drift guard: the founder moving a post out of the box's lane aborts work.

At every milestone the poller re-reads the post's decision status before
mirroring. A post that has left the active box lane (Cancelled / Needs
Refinement / Rejected / Open for Vote) is a human decision the box must NOT
overwrite — it escalates the store row and stops working the issue, never
calling ``set_status``.

These tests also pin the best-effort discipline: a ``set_status`` failure must
not break the tick loop, and a mirror-time read error must not falsely abort.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.poller import Poller
from wgmesh_pipeline.state.store import StateStore


class DriftForge:
    """Quackback-shaped forge with a programmable decision-status read.

    ``status_source`` is either a fixed string or a zero-arg callable returning
    the current status (so a test can flip it to "Cancelled" mid-run). A read
    error is simulated by a callable that raises.
    """

    def __init__(
        self,
        status_source: str | Callable[[], str | None] = "Building",
        *,
        pr: dict | None = None,
        set_status_error: Exception | None = None,
    ):
        self._status_source = status_source
        self.pr = pr if pr is not None else {"number": 99, "merged": True}
        self._set_status_error = set_status_error
        self.set_status_calls: list[tuple[int, str]] = []
        self.labels: list[tuple[int, str]] = []
        self.auto_merge: list[int] = []
        self.bound_resolver: Any = None

    def bind_resolver(self, resolver: Any) -> None:
        self.bound_resolver = resolver

    def get_decision_status(self, number: int) -> str | None:
        if callable(self._status_source):
            return self._status_source()
        return self._status_source

    def set_status(self, number: int, status: str) -> Any:
        if self._set_status_error is not None:
            raise self._set_status_error
        self.set_status_calls.append((number, status))
        return {"ok": True}

    def list_accepted_posts(self) -> list[dict[str, Any]]:
        # Tests seed the store directly via upsert_issue; ingest is a no-op here.
        return []

    def get_pr(self, number: int) -> dict[str, Any]:
        return dict(self.pr)

    def enable_auto_merge(self, pr_number: int, *, merge_method: str = "SQUASH") -> Any:
        self.auto_merge.append(pr_number)
        return {"ok": True}

    def add_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any:
        self.labels.append((issue_number, label))
        return {"ok": True}


class MergeGraph:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def triage(self, state):
        self.calls.append("triage")
        return {**state, "classification": "fix"}

    def spec(self, state):
        self.calls.append("spec")
        return {**state, "spec_path": "specs/issue.md"}

    def spec_pr(self, state):
        self.calls.append("spec_pr")
        return {**state, "spec_pr": 88}

    def implement(self, state):
        self.calls.append("implement")
        return {
            **state,
            "diff": "+x\n",
            "changed_files": ["docs/readme.md"],
            "impl_pr": 99,
        }

    def review(self, state):
        self.calls.append("review")
        return {
            **state,
            "tests_passed": True,
            "sanitise_ok": True,
            "review_findings": [],
        }


@pytest.fixture
def cfg() -> Config:
    return Config(
        target_repo="o/r",
        mode="live",
        max_files=3,
        forge_kind="quackback",
        quackback_url="https://qb.example.com",
        quackback_token="qb_token",
    )


@pytest.fixture
def github_cfg() -> Config:
    return Config(target_repo="o/r", mode="live", max_files=3, forge_kind="github")


def _poller(tmp_path, cfg, forge, graph=None):
    store = StateStore(tmp_path / "state.db")
    return Poller(config=cfg, store=store, client=forge, graph=graph or MergeGraph())


def _no_score(monkeypatch) -> list[str]:
    scored: list[str] = []
    monkeypatch.setattr(
        "wgmesh_pipeline.poller.score_run",
        lambda state, *, outcome: scored.append(outcome),
    )
    return scored


# --------------------------------------------------------------------------- U12


def test_drift_at_claim_aborts_and_escalates(tmp_path, cfg, monkeypatch) -> None:
    _no_score(monkeypatch)
    forge = DriftForge("Cancelled")
    graph = MergeGraph()
    p = _poller(tmp_path, cfg, forge, graph)
    p.store.upsert_issue(1, "Cancelled before claim")

    asyncio.run(p.tick())  # queued -> triaged, then drift re-read aborts.

    assert p.store.get_issue(1).stage == "escalated"
    assert forge.set_status_calls == []  # never overwrite a human decision
    # No spec/PR work after the abort.
    assert "spec" not in graph.calls
    assert "implement" not in graph.calls


def test_drift_needs_refinement_at_claim_aborts(tmp_path, cfg, monkeypatch) -> None:
    _no_score(monkeypatch)
    forge = DriftForge("Needs Refinement")
    p = _poller(tmp_path, cfg, forge)
    p.store.upsert_issue(1, "Needs refinement mid-build")

    asyncio.run(p.tick())

    assert p.store.get_issue(1).stage == "escalated"
    assert forge.set_status_calls == []


def test_drift_after_pr_open_before_merge_no_ship(tmp_path, cfg, monkeypatch) -> None:
    _no_score(monkeypatch)
    # In lane until the issue reaches awaiting_merge, then the founder Cancels.
    state = {"value": "Accepted for Build"}
    forge = DriftForge(
        lambda: state["value"],
        pr={"number": 99, "merged": True},
    )
    p = _poller(tmp_path, cfg, forge)
    p.store.upsert_issue(1, "Cancel after PR open")

    # Drive up to awaiting_merge (stop before the merge tick).
    for _ in range(20):
        issue = p.store.get_issue(1)
        if issue.stage == "awaiting_merge":
            break
        if issue.stage in {"escalated", "failed", "merged"}:
            break
        asyncio.run(p.tick())
    assert p.store.get_issue(1).stage == "awaiting_merge"

    # Founder cancels; the awaiting_merge tick re-reads drift before Shipped.
    state["value"] = "Cancelled"
    asyncio.run(p.tick())

    assert p.store.get_issue(1).stage == "escalated"
    statuses = [s for _, s in forge.set_status_calls]
    assert "Shipped" not in statuses  # human status untouched


# ---------------------------------------------------------------- best-effort


def test_set_status_error_does_not_break_loop(tmp_path, cfg, monkeypatch) -> None:
    _no_score(monkeypatch)
    forge = DriftForge(
        "Accepted for Build",
        pr={"number": 99, "merged": True},
        set_status_error=RuntimeError("qb down"),
    )
    p = _poller(tmp_path, cfg, forge)
    p.store.upsert_issue(1, "QB write fails but merge records")

    # No exception should escape into the loop; the issue still reaches merged.
    for _ in range(20):
        issue = p.store.get_issue(1)
        if issue.stage in {"merged", "escalated", "failed"}:
            break
        asyncio.run(p.tick())

    assert p.store.get_issue(1).stage == "merged"


def test_mirror_read_error_is_non_fatal(tmp_path, cfg, monkeypatch) -> None:
    _no_score(monkeypatch)

    def boom() -> str:
        raise RuntimeError("qb read down")

    forge = DriftForge(boom, pr={"number": 99, "merged": True})
    p = _poller(tmp_path, cfg, forge)
    p.store.upsert_issue(1, "Read errors but work continues")

    # A mirror-time read error must NOT falsely abort: the first claim continues.
    advanced = asyncio.run(p.tick())
    assert advanced is not None
    assert p.store.get_issue(1).stage == "triaged"


# ---------------------------------------------------------------- github no-op


def test_github_forge_kind_is_noop(tmp_path, github_cfg) -> None:
    forge = DriftForge("Cancelled")  # would abort if consulted
    p = _poller(tmp_path, github_cfg, forge)

    # github forge: bind_resolver must not have been called, and _mirror_quackback
    # is a pure no-op returning True regardless of the (would-be-drifting) status.
    assert forge.bound_resolver is None
    assert p._mirror_quackback(1, "triaged") is True
    assert forge.set_status_calls == []
