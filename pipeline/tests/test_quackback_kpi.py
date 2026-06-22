"""Cutover U3: queue-health KPI repointed from GitHub issues to the Quackback board.

Once Build Suggestions live on the Quackback board (not GitHub Issues), the
queue-health signal becomes **posts-by-decision-status** + **oldest-undecided
age**. These tests drive that collector against a recorded fake — no live API —
and pin the fail-closed-loud contract on the gating reads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from wgmesh_pipeline.forge.quackback_client import QuackbackError
from wgmesh_pipeline.quackback_kpi import (
    collect_quackback_queue_health,
    select_queue_health,
)

NOW = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)

# The 8 board statuses (name, slug) the live board carries.
_STATUSES = [
    {"id": "s_ofv", "name": "Open for Vote", "slug": "open-for-vote"},
    {"id": "s_nr", "name": "Needs Refinement", "slug": "needs-refinement"},
    {"id": "s_afb", "name": "Accepted for Build", "slug": "accepted-for-build"},
    {"id": "s_bld", "name": "Building", "slug": "building"},
    {"id": "s_rfr", "name": "Ready for Review", "slug": "ready-for-review"},
    {"id": "s_shp", "name": "Shipped", "slug": "shipped"},
    {"id": "s_rej", "name": "Rejected", "slug": "rejected"},
    {"id": "s_can", "name": "Cancelled", "slug": "cancelled"},
]


class FakeReader:
    """Records calls; returns posts keyed by status slug. Optionally raises on a
    chosen slug to exercise the fail-closed-loud gating contract."""

    def __init__(
        self,
        posts_by_slug: dict[str, list[dict[str, Any]]],
        *,
        statuses: list[dict[str, Any]] | None = None,
        raise_on_slug: str | None = None,
    ) -> None:
        self._posts = posts_by_slug
        self._statuses = statuses if statuses is not None else _STATUSES
        self._raise_on_slug = raise_on_slug
        self.calls: list[tuple[str, Any]] = []

    def list_statuses(self) -> list[dict[str, Any]]:
        self.calls.append(("list_statuses", None))
        return list(self._statuses)

    def list_posts(
        self,
        status_slug: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("list_posts", status_slug))
        if status_slug == self._raise_on_slug:
            raise QuackbackError(f"boom on {status_slug}")
        data = list(self._posts.get(status_slug or "", []))
        return {"data": data, "meta": {"pagination": {"hasMore": False}}}


def _post(pid: str, created: str) -> dict[str, Any]:
    return {"id": pid, "title": pid, "createdAt": created}


def test_posts_by_status_maps_all_eight_slugs_to_counts() -> None:
    reader = FakeReader(
        {
            "open-for-vote": [_post("p1", "2026-06-22T09:00:00Z")],
            "needs-refinement": [],
            "accepted-for-build": [
                _post("p2", "2026-06-21T00:00:00Z"),
                _post("p3", "2026-06-21T01:00:00Z"),
            ],
            "building": [_post("p4", "2026-06-20T00:00:00Z")],
            "ready-for-review": [],
            "shipped": [
                _post("p5", "2026-06-19T00:00:00Z"),
                _post("p6", "2026-06-18T00:00:00Z"),
                _post("p7", "2026-06-17T00:00:00Z"),
            ],
            "rejected": [],
            "cancelled": [],
        }
    )

    out = collect_quackback_queue_health(reader, now=NOW)

    assert out["source"] == "quackback"
    assert out["posts_by_decision_status"] == {
        "Open for Vote": 1,
        "Needs Refinement": 0,
        "Accepted for Build": 2,
        "Building": 1,
        "Ready for Review": 0,
        "Shipped": 3,
        "Rejected": 0,
        "Cancelled": 0,
    }


def test_oldest_undecided_age_from_oldest_open_for_vote_or_needs_refinement() -> None:
    reader = FakeReader(
        {
            # oldest undecided is the needs-refinement post at 06-20T12:00 → 48h
            "open-for-vote": [_post("p1", "2026-06-22T06:00:00Z")],
            "needs-refinement": [_post("p2", "2026-06-20T12:00:00Z")],
            # a much older Shipped post must NOT count (not undecided)
            "shipped": [_post("p9", "2026-01-01T00:00:00Z")],
        }
    )

    out = collect_quackback_queue_health(reader, now=NOW)

    assert out["oldest_undecided_age_seconds"] == 48 * 3600
    assert out["oldest_undecided_age_hours"] == 48.0


def test_empty_board_yields_zero_counts_and_null_age_not_error() -> None:
    reader = FakeReader({slug["slug"]: [] for slug in _STATUSES})

    out = collect_quackback_queue_health(reader, now=NOW)

    assert set(out["posts_by_decision_status"].values()) == {0}
    assert out["oldest_undecided_age_seconds"] is None
    assert out["oldest_undecided_age_hours"] is None


def test_api_error_on_a_gating_count_fails_closed_loud() -> None:
    reader = FakeReader(
        {"open-for-vote": [_post("p1", "2026-06-22T09:00:00Z")]},
        raise_on_slug="building",
    )

    with pytest.raises(QuackbackError, match="boom on building"):
        collect_quackback_queue_health(reader, now=NOW)


def test_select_queue_health_github_returns_github_block_unchanged() -> None:
    gh = {"issues_by_function_label": {"fn:dev": 3}}
    qb = {"posts_by_decision_status": {"Open for Vote": 1}}

    assert select_queue_health("github", github_block=gh, quackback_block=qb) is gh
    assert select_queue_health(None, github_block=gh, quackback_block=qb) is gh


def test_select_queue_health_quackback_returns_board_block() -> None:
    gh = {"issues_by_function_label": {"fn:dev": 3}}
    qb = {"posts_by_decision_status": {"Open for Vote": 1}}

    assert select_queue_health("quackback", github_block=gh, quackback_block=qb) is qb
