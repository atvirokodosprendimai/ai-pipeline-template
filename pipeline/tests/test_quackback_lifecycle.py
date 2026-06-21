"""U6 — box execution milestones mirror to the Quackback post status.

The poller drives a post through its lane and flips the mirrored Quackback
status at each milestone:

  - first real claim (queued -> triaged)  -> "Building"
  - review gate decides to merge           -> "Ready for Review"
  - the impl PR actually merges            -> "Shipped" (real merge only)

These tests use a controllable fake forge + a real temp store and assert the
``set_status`` calls + that ``score_run(outcome="merged")`` fires exactly once on
a real merge — and never flips Shipped while the PR is unmerged.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.poller import Poller
from wgmesh_pipeline.state.store import StateStore


class FakeForge:
    """A Quackback-shaped forge: records set_status, serves a drift-controllable
    decision status, and stands in for the PR backend (get_pr/enable_auto_merge/
    add_label)."""

    def __init__(self, *, decision_status: str = "Building", pr: dict | None = None):
        self.decision_status = decision_status
        self.pr = pr if pr is not None else {"number": 99, "merged": True}
        self.set_status_calls: list[tuple[int, str]] = []
        self.bound_resolver: Any = None
        self.labels: list[tuple[int, str]] = []
        self.auto_merge: list[int] = []

    # --- U6 read/write surface -------------------------------------------------
    def bind_resolver(self, resolver: Any) -> None:
        self.bound_resolver = resolver

    def get_decision_status(self, number: int) -> str | None:
        return self.decision_status

    def set_status(self, number: int, status: str) -> Any:
        self.set_status_calls.append((number, status))
        # A box-set status keeps the post in-lane (mirrors real behavior).
        self.decision_status = status
        return {"ok": True}

    # --- ingest (reconcile_quackback runs every tick) --------------------------
    def list_accepted_posts(self) -> list[dict[str, Any]]:
        # Tests seed the store directly via upsert_issue; ingest is a no-op here.
        return []

    # --- PR backend ------------------------------------------------------------
    def get_pr(self, number: int) -> dict[str, Any]:
        return dict(self.pr)

    def enable_auto_merge(self, pr_number: int, *, merge_method: str = "SQUASH") -> Any:
        self.auto_merge.append(pr_number)
        return {"ok": True}

    def add_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any:
        self.labels.append((issue_number, label))
        return {"ok": True}


class MergeGraph:
    """Fake graph whose review output drives the gate to decision=merge."""

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


def _poller(tmp_path, cfg, forge):
    store = StateStore(tmp_path / "state.db")
    return Poller(config=cfg, store=store, client=forge, graph=MergeGraph())


def _drive_to_merge(p: Poller, number: int) -> None:
    """Tick through every stage queued -> ... -> merged."""
    for _ in range(20):
        issue = p.store.get_issue(number)
        if issue.stage in {"merged", "escalated", "failed"}:
            break
        asyncio.run(p.tick())


def test_lifecycle_mirrors_building_review_shipped(tmp_path, cfg, monkeypatch) -> None:
    scored: list[str] = []
    monkeypatch.setattr(
        "wgmesh_pipeline.poller.score_run",
        lambda state, *, outcome: scored.append(outcome),
    )
    forge = FakeForge(
        decision_status="Accepted for Build", pr={"number": 99, "merged": True}
    )
    p = _poller(tmp_path, cfg, forge)
    p.store.upsert_issue(1, "Ship it")

    _drive_to_merge(p, 1)

    assert p.store.get_issue(1).stage == "merged"
    statuses = [s for _, s in forge.set_status_calls]
    assert "Building" in statuses
    assert "Ready for Review" in statuses
    assert "Shipped" in statuses
    # Order: Building before Ready for Review before Shipped.
    assert statuses.index("Building") < statuses.index("Ready for Review")
    assert statuses.index("Ready for Review") < statuses.index("Shipped")
    assert scored.count("merged") == 1


def test_resolver_bound_on_quackback_poller(tmp_path, cfg) -> None:
    forge = FakeForge()
    p = _poller(tmp_path, cfg, forge)
    assert forge.bound_resolver == p.store.quackback_post_id_for


def test_shipped_only_on_real_merge(tmp_path, cfg, monkeypatch) -> None:
    scored: list[str] = []
    monkeypatch.setattr(
        "wgmesh_pipeline.poller.score_run",
        lambda state, *, outcome: scored.append(outcome),
    )
    # PR is open, not merged: awaiting_merge must NOT flip Shipped or transition.
    forge = FakeForge(
        decision_status="Accepted for Build",
        pr={"number": 99, "merged": False, "state": "open"},
    )
    p = _poller(tmp_path, cfg, forge)
    p.store.upsert_issue(1, "Ship it")

    _drive_to_merge(p, 1)

    assert p.store.get_issue(1).stage == "awaiting_merge"
    statuses = [s for _, s in forge.set_status_calls]
    assert "Shipped" not in statuses
    assert "merged" not in scored
