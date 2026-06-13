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


def test_injected_connection_adapter_roundtrip() -> None:
    # libsql returns plain tuples and rejects row_factory; the _LibsqlConn
    # adapter must present sqlite3-Row-style mapping rows. A tuple-returning
    # sqlite3 connection (no row_factory) stands in for a libsql connection and
    # exercises the same adapter path verified live against Turso.
    import sqlite3

    raw = sqlite3.connect(":memory:")  # returns tuples, has .description + executescript
    db = StateStore(connection=raw)  # wrapped in _LibsqlConn
    db.upsert_issue(7, "via adapter")
    got = db.get_issue(7)
    assert got.number == 7 and got.stage == "queued" and got.title == "via adapter"
    assert db.transition(7, "queued", "triaged").stage == "triaged"
    db.record_run(issue=7, node="queued", outcome="ok")
    assert len(db.list_runs()) == 1
    # migrations tracked through the adapter
    versions = [r["version"] for r in db._conn.execute("SELECT version FROM schema_migrations").fetchall()]
    assert versions == ["0001", "0002"]


def test_reset_queue_clears_issues_and_runs_idempotently(tmp_path) -> None:
    db = store(tmp_path)
    db.upsert_issue(1, "queued")
    db.upsert_issue(2, "specced", stage="specced")
    db.record_run(issue=1, node="queued", outcome="ok")
    db.record_run(issue=2, node="specced", outcome="ok")

    cleared = db.reset_queue()
    cleared_again = db.reset_queue()

    assert cleared == {"issues": 2, "runs": 2}
    assert cleared_again == {"issues": 0, "runs": 0}
    assert db.list_issues() == []
    assert db.list_runs() == []
    versions = [r["version"] for r in db._conn.execute("SELECT version FROM schema_migrations").fetchall()]
    assert versions == ["0001", "0002"]


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
    assert versions == ["0001", "0002"]


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


def test_spec_opened_transitions_to_spec_ready_only(tmp_path) -> None:
    db = store(tmp_path)
    db.upsert_issue(1, "Spec opened", stage="spec_opened")

    assert db.transition(1, "spec_opened", "spec_ready").stage == "spec_ready"

    db.upsert_issue(2, "Spec opened", stage="spec_opened")
    with pytest.raises(TransitionError, match="spec_opened->implemented"):
        db.transition(2, "spec_opened", "implemented")


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


def test_error_stats_reports_per_node_rates_and_failed_issue_counts(tmp_path) -> None:
    db = store(tmp_path)
    now = datetime(2026, 6, 8, 12, tzinfo=timezone.utc)
    db.upsert_issue(1, "failed", stage="failed", last_error="boom", updated_at=now)
    db.upsert_issue(2, "errored", stage="queued", last_error="temporary", updated_at=now)
    db.record_run(issue=1, node="queued", outcome="ok", started=now - timedelta(minutes=5))
    db.record_run(issue=1, node="queued", outcome="error", started=now - timedelta(minutes=4))
    db.record_run(issue=2, node="reviewed", outcome="error", started=now - timedelta(minutes=3))

    stats = db.error_stats(timedelta(minutes=15), now=now)

    assert stats["failed_issues"] == 1
    assert stats["issues_with_last_error"] == 2
    assert stats["nodes"]["queued"] == {"ok": 1, "error": 1, "total": 2, "error_rate": 0.5}
    assert stats["nodes"]["reviewed"] == {"ok": 0, "error": 1, "total": 1, "error_rate": 1.0}
    assert stats["last_errors"][0]["stage"] == "failed"
    assert stats["last_errors"][0]["last_error"] == "boom"


def test_error_stats_excludes_runs_older_than_window(tmp_path) -> None:
    db = store(tmp_path)
    now = datetime(2026, 6, 8, 12, tzinfo=timezone.utc)
    db.upsert_issue(1, "old")
    db.record_run(issue=1, node="queued", outcome="error", started=now - timedelta(minutes=16))
    db.record_run(issue=1, node="queued", outcome="ok", started=now - timedelta(minutes=2))

    stats = db.error_stats(timedelta(minutes=15), now=now)

    assert stats["nodes"]["queued"] == {"ok": 1, "error": 0, "total": 1, "error_rate": 0.0}


def test_error_stats_zero_error_store_returns_zero_rates(tmp_path) -> None:
    db = store(tmp_path)
    now = datetime(2026, 6, 8, 12, tzinfo=timezone.utc)
    db.upsert_issue(1, "clean")
    db.record_run(issue=1, node="queued", outcome="ok", started=now - timedelta(minutes=1))

    stats = db.error_stats(timedelta(minutes=15), now=now)

    assert stats["failed_issues"] == 0
    assert stats["issues_with_last_error"] == 0
    assert stats["nodes"]["queued"]["error_rate"] == 0.0
    assert stats["last_errors"] == []


def test_error_stats_failed_issue_outside_window_self_clears(tmp_path) -> None:
    """Windowed issue counts so the error-rate alert self-recovers: a failed
    issue last touched before the window must not keep the alert latched red."""
    db = store(tmp_path)
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    db.upsert_issue(1, "old failure", stage="failed", updated_at=now - timedelta(minutes=30))
    stats = db.error_stats(timedelta(minutes=15), now=now)
    assert stats["failed_issues"] == 0
    db.upsert_issue(2, "recent failure", stage="failed", updated_at=now - timedelta(minutes=5))
    stats2 = db.error_stats(timedelta(minutes=15), now=now)
    assert stats2["failed_issues"] == 1


# --- control-loop module state (U3) -----------------------------------------


def test_control_state_roundtrip(tmp_path) -> None:
    db = store(tmp_path)
    assert db.load_control_state("supervisor-rank-state") is None
    doc = {"top": [{"id": "wgmesh#727"}], "material_fingerprint": "abc"}
    assert db.save_control_state("supervisor-rank-state", doc, fingerprint="abc") is True
    loaded = db.load_control_state("supervisor-rank-state")
    assert loaded == doc


def test_control_state_dedupes_on_fingerprint(tmp_path) -> None:
    db = store(tmp_path)
    doc = {"x": 1}
    assert db.save_control_state("pipeline-health-state", doc, fingerprint="f1") is True
    # same fingerprint -> no write
    assert db.save_control_state("pipeline-health-state", {"x": 2}, fingerprint="f1") is False
    assert db.load_control_state("pipeline-health-state") == {"x": 1}
    # changed fingerprint -> writes the new doc
    assert db.save_control_state("pipeline-health-state", {"x": 2}, fingerprint="f2") is True
    assert db.load_control_state("pipeline-health-state") == {"x": 2}


def test_control_state_empty_fingerprint_always_writes(tmp_path) -> None:
    # An empty fingerprint never dedupes (modules without a material fingerprint
    # still get the latest copy persisted).
    db = store(tmp_path)
    assert db.save_control_state("k", {"a": 1}, fingerprint="") is True
    assert db.save_control_state("k", {"a": 2}, fingerprint="") is True
    assert db.load_control_state("k") == {"a": 2}
