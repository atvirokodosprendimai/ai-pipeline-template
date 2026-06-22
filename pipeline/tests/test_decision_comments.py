"""Decision-lane comment author-distinction + iteration state (U4)."""

from __future__ import annotations

from wgmesh_pipeline.decision_lane.comments import (
    is_unprocessed,
    latest_cofounder_comment,
)
from wgmesh_pipeline.state.store import StateStore

BOT = "autobox-box"


def _c(cid, author, *, team=True, created="2026-06-22T10:00:00Z"):
    return {
        "id": cid,
        "authorName": author,
        "isTeamMember": team,
        "createdAt": created,
    }


def test_ignores_bot_own_comment() -> None:
    comments = [_c("c1", BOT)]
    assert latest_cofounder_comment(comments, BOT) is None


def test_ignores_non_team_comment() -> None:
    comments = [_c("c1", "random_user", team=False)]
    assert latest_cofounder_comment(comments, BOT) is None


def test_selects_newest_cofounder_comment() -> None:
    comments = [
        _c("c1", "marty", created="2026-06-22T09:00:00Z"),
        _c("c2", "lempa", created="2026-06-22T11:00:00Z"),
        _c("c3", BOT, created="2026-06-22T12:00:00Z"),  # bot reply, ignored
    ]
    latest = latest_cofounder_comment(comments, BOT)
    assert latest is not None and latest["id"] == "c2"


def test_is_unprocessed_against_marker() -> None:
    c = _c("c2", "marty")
    assert is_unprocessed(c, last_comment_id="c1") is True
    assert is_unprocessed(c, last_comment_id="c2") is False
    assert is_unprocessed(c, last_comment_id=None) is True  # first feedback
    assert is_unprocessed(None, last_comment_id="c1") is False


def test_decision_state_round_trip_and_iteration_cap(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    assert store.get_decision_state("post_01") is None

    assert store.record_decision_proposal("post_01", last_comment_id=None) == 1
    state = store.get_decision_state("post_01")
    assert state == {"last_comment_id": None, "iterations": 1}

    assert store.record_decision_proposal("post_01", last_comment_id="c2") == 2
    state = store.get_decision_state("post_01")
    assert state == {"last_comment_id": "c2", "iterations": 2}


def test_migration_0005_adds_decision_posts_table(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    row = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='decision_posts'"
    ).fetchone()
    assert row is not None
