from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dataclasses import dataclass

from wgmesh_pipeline.state.store import StateStore, TransitionError, open_state_store


def store(tmp_path):
    return StateStore(tmp_path / "state.db")


@dataclass
class _DbCfg:
    database_mode: str
    database_path: str = "x.db"
    turso_url: str | None = None
    turso_auth_token: str | None = None


def test_open_state_store_local(tmp_path) -> None:
    db = open_state_store(_DbCfg(database_mode="local", database_path=str(tmp_path / "s.db")))
    db.upsert_issue(1, "ok")
    assert db.get_issue(1).stage == "queued"


def test_open_state_store_turso_fails_loud_never_falls_back_local() -> None:
    # No silent fallback: turso selected but unreachable/unavailable must raise,
    # never silently return a local store. (RuntimeError if libsql absent; a
    # conn/libsql error if present + bogus url — either way, it raises.)
    import pytest as _pytest

    with _pytest.raises(Exception):
        open_state_store(_DbCfg(database_mode="turso", turso_url="libsql://nonexistent.invalid"))


def test_open_state_store_unknown_mode_raises() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError, match="database_mode"):
        open_state_store(_DbCfg(database_mode="bogus"))


def test_upsert_and_transition_persist(tmp_path) -> None:
    db = store(tmp_path)
    db.upsert_issue(1, "Fix relay")

    db.transition(1, "queued", "triaged")
    db.transition(1, "triaged", "specced")

    issue = db.get_issue(1)
    assert issue.stage == "specced"
    assert issue.title == "Fix relay"


def test_migrations_apply_idempotently(tmp_path) -> None:
    db = store(tmp_path)
    # already migrated on open; re-running applies nothing new
    assert db.migrate() == []
    db.upsert_issue(1, "Still works")
    assert db.get_issue(1).stage == "queued"
    # schema_migrations records the initial migration exactly once
    versions = [r["version"] for r in db._conn.execute("SELECT version FROM schema_migrations").fetchall()]
    assert versions == ["0001"]


def test_sqlite_connection_uses_wal_and_busy_timeout(tmp_path) -> None:
    db = store(tmp_path)

    busy_timeout = db._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    journal_mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert busy_timeout == 5000
    assert journal_mode == "wal"


def test_illegal_transition_rejected(tmp_path) -> None:
    db = store(tmp_path)
    db.upsert_issue(1, "Done", stage="merged")

    with pytest.raises(TransitionError, match="merged->queued"):
        db.transition(1, "merged", "queued")


def test_claim_next_skips_cooldown_and_returns_eldest_eligible(tmp_path) -> None:
    db = store(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    db.upsert_issue(1, "cooling", updated_at=now, stage="queued")
    db.bump_attempt(1, "temporary", now=now)
    db.upsert_issue(2, "newer eligible", updated_at=now - timedelta(minutes=5), stage="queued")
    db.upsert_issue(3, "eldest eligible", updated_at=now - timedelta(minutes=10), stage="queued")

    claimed = db.claim_next(now=now + timedelta(seconds=30))

    assert claimed is not None
    assert claimed.number == 3


def test_dedup_upsert_updates_without_duplicate(tmp_path) -> None:
    db = store(tmp_path)
    db.upsert_issue(1, "old")
    db.upsert_issue(1, "new")

    assert db.get_issue(1).title == "new"
    assert [issue.number for issue in db.list_issues()] == [1]


def test_bump_attempt_records_error_and_fails_after_limit(tmp_path) -> None:
    db = store(tmp_path)
    db.upsert_issue(1, "flaky")

    first = db.bump_attempt(1, "first", max_attempts=2)
    second = db.bump_attempt(1, "second", max_attempts=2)

    assert first.attempts == 1
    assert first.stage == "queued"
    assert second.attempts == 2
    assert second.stage == "failed"
    assert second.last_error == "second"
