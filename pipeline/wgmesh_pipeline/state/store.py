from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Sequence


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"triaged", "escalated", "failed"},
    "triaged": {"specced", "escalated", "failed"},
    "specced": {"spec_ready", "spec_opened", "escalated", "failed"},
    "spec_ready": {"implemented", "escalated", "failed"},
    "implemented": {"reviewed", "escalated", "failed"},
    "reviewed": {"merged", "escalated", "failed"},
    "spec_opened": {"spec_ready"},
    "merged": set(),
    "escalated": set(),
    "failed": set(),
}
ACTIONABLE_STAGES = ("queued", "triaged", "specced", "spec_ready", "implemented", "reviewed")


class TransitionError(ValueError):
    pass


@dataclass(frozen=True)
class IssueRecord:
    number: int
    title: str
    classification: str | None
    stage: str
    status: str
    risk_tier: str | None
    attempts: int
    spec_pr: int | None
    impl_pr: int | None
    last_error: str | None
    updated_at: datetime


class StateStore:
    def __init__(self, path: str | Path | None = None, *, connection: Any = None):
        # Local SQLite (path) or an injected libsql/Turso connection. Both run
        # the same versioned migrations — mirrors mailservice's OpenAndMigrate /
        # OpenTurso, where both paths call migrate().
        if connection is not None:
            self.path = None
            # libsql returns plain tuples and rejects row_factory; adapt it to
            # the sqlite3-Row mapping interface the rest of the store expects.
            self._conn = _LibsqlConn(connection)
        else:
            self.path = str(path)
            self._conn = sqlite3.connect(self.path)
            # WAL + busy_timeout only apply to a local file db; a Turso/libsql
            # server manages its own journaling.
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.row_factory = sqlite3.Row
        self.migrate()

    def close(self) -> None:
        self._conn.close()

    def migrate(self) -> list[str]:
        """Apply pending versioned migrations in order; return versions applied
        this call. Tracked in schema_migrations so each runs exactly once."""
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        self._conn.commit()
        applied = {
            str(row["version"])
            for row in self._conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        newly: list[str] = []
        for version, sql in _load_migrations():
            if version in applied:
                continue
            self._conn.executescript(sql)
            self._conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, _iso(_now())),
            )
            self._conn.commit()
            newly.append(version)
        return newly

    def upsert_issue(
        self,
        number: int,
        title: str,
        *,
        classification: str | None = None,
        stage: str = "queued",
        status: str = "open",
        risk_tier: str | None = None,
        spec_pr: int | None = None,
        impl_pr: int | None = None,
        last_error: str | None = None,
        updated_at: datetime | None = None,
    ) -> IssueRecord:
        if stage not in ALLOWED_TRANSITIONS:
            raise ValueError(f"unknown issue stage: {stage}")
        now = _dt(updated_at)
        self._conn.execute(
            """
            INSERT INTO issues (
              number, title, classification, stage, status, risk_tier,
              attempts, spec_pr, impl_pr, last_error, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            ON CONFLICT(number) DO UPDATE SET
              title=excluded.title,
              classification=COALESCE(excluded.classification, issues.classification),
              stage=excluded.stage,
              status=excluded.status,
              risk_tier=COALESCE(excluded.risk_tier, issues.risk_tier),
              spec_pr=COALESCE(excluded.spec_pr, issues.spec_pr),
              impl_pr=COALESCE(excluded.impl_pr, issues.impl_pr),
              last_error=excluded.last_error,
              updated_at=excluded.updated_at
            """,
            (
                number,
                title,
                classification,
                stage,
                status,
                risk_tier,
                spec_pr,
                impl_pr,
                last_error,
                _iso(now),
            ),
        )
        self._conn.commit()
        return self.get_issue(number)

    def get_issue(self, number: int) -> IssueRecord:
        row = self._conn.execute("SELECT * FROM issues WHERE number = ?", (number,)).fetchone()
        if row is None:
            raise KeyError(f"issue {number} not found")
        return _issue(row)

    def list_issues(self) -> list[IssueRecord]:
        rows = self._conn.execute("SELECT * FROM issues ORDER BY number").fetchall()
        return [_issue(row) for row in rows]

    def transition(self, number: int, from_stage: str, to_stage: str) -> IssueRecord:
        if to_stage not in ALLOWED_TRANSITIONS:
            raise TransitionError(f"unknown destination stage: {to_stage}")
        allowed = ALLOWED_TRANSITIONS.get(from_stage)
        if allowed is None or to_stage not in allowed:
            raise TransitionError(f"illegal transition {from_stage}->{to_stage}")
        now = _now()
        cursor = self._conn.execute(
            """
            UPDATE issues
               SET stage = ?, updated_at = ?
             WHERE number = ? AND stage = ?
            """,
            (to_stage, _iso(now), number, from_stage),
        )
        if cursor.rowcount != 1:
            current = self.get_issue(number).stage
            raise TransitionError(f"issue {number} is at {current}, not {from_stage}")
        self._conn.commit()
        return self.get_issue(number)

    def set_stage(self, number: int, stage: str, *, status: str | None = None) -> IssueRecord:
        if stage not in ALLOWED_TRANSITIONS:
            raise ValueError(f"unknown issue stage: {stage}")
        self._conn.execute(
            """
            UPDATE issues
               SET stage = ?, status = COALESCE(?, status), updated_at = ?
             WHERE number = ?
            """,
            (stage, status, _iso(_now()), number),
        )
        self._conn.commit()
        return self.get_issue(number)

    def claim_next(
        self,
        *,
        now: datetime | None = None,
        stages: tuple[str, ...] = ACTIONABLE_STAGES,
    ) -> IssueRecord | None:
        current = _dt(now)
        rows = self._conn.execute(
            f"""
            SELECT * FROM issues
             WHERE status = 'open'
               AND stage IN ({",".join("?" for _ in stages)})
             ORDER BY updated_at ASC, number ASC
            """,
            stages,
        ).fetchall()
        for row in rows:
            issue = _issue(row)
            if issue.updated_at + _cooldown(issue.attempts) <= current:
                return issue
        return None

    def record_run(
        self,
        *,
        issue: int,
        node: str,
        outcome: str,
        started: datetime | None = None,
        ended: datetime | None = None,
        langsmith_run_id: str | None = None,
        tokens: int | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO runs(issue, node, started, ended, outcome, langsmith_run_id, tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue,
                node,
                _iso(_dt(started)),
                _iso(_dt(ended)) if ended is not None else None,
                outcome,
                langsmith_run_id,
                tokens,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def list_runs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM runs ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def error_stats(self, window: timedelta, *, now: datetime | None = None) -> dict[str, Any]:
        """Return recent per-node error rates and issue error counts."""
        cutoff = _iso(_dt(now) - window)
        rows = self._conn.execute(
            """
            SELECT
              node,
              SUM(CASE WHEN outcome = 'ok' THEN 1 ELSE 0 END) AS ok_count,
              SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END) AS error_count
            FROM runs
            WHERE started >= ?
              AND outcome IN ('ok', 'error')
            GROUP BY node
            ORDER BY node
            """,
            (cutoff,),
        ).fetchall()
        nodes: dict[str, dict[str, Any]] = {}
        for row in rows:
            ok = int(row["ok_count"] or 0)
            error = int(row["error_count"] or 0)
            total = ok + error
            nodes[str(row["node"])] = {
                "ok": ok,
                "error": error,
                "total": total,
                "error_rate": error / total if total else 0.0,
            }

        # Window the issue-level counts by updated_at the same way as run rates.
        # Without the window these counts are monotonic ('failed' is terminal and
        # last_error is never cleared), so the alert would latch permanently red
        # and never self-recover once any issue ever failed.
        failed_issues = int(
            self._conn.execute(
                "SELECT COUNT(*) AS count FROM issues WHERE stage = 'failed' AND updated_at >= ?",
                (cutoff,),
            ).fetchone()["count"]
        )
        issues_with_last_error = int(
            self._conn.execute(
                "SELECT COUNT(*) AS count FROM issues "
                "WHERE last_error IS NOT NULL AND last_error != '' AND updated_at >= ?",
                (cutoff,),
            ).fetchone()["count"]
        )
        last_error_rows = self._conn.execute(
            """
            SELECT number, stage, substr(last_error, 1, 400) AS last_error
            FROM issues
            WHERE last_error IS NOT NULL AND last_error != ''
              AND updated_at >= ?
            ORDER BY updated_at DESC, number ASC
            LIMIT 20
            """,
            (cutoff,),
        ).fetchall()
        return {
            "nodes": nodes,
            "failed_issues": failed_issues,
            "issues_with_last_error": issues_with_last_error,
            "last_errors": [
                {"issue": int(row["number"]), "stage": str(row["stage"]), "last_error": str(row["last_error"])}
                for row in last_error_rows
            ],
        }

    def reset_queue(self) -> dict[str, int]:
        """Clear durable pipeline work state while leaving migrations intact."""
        issue_count = int(self._conn.execute("SELECT COUNT(*) AS count FROM issues").fetchone()["count"])
        run_count = int(self._conn.execute("SELECT COUNT(*) AS count FROM runs").fetchone()["count"])
        self._conn.execute("DELETE FROM runs")
        self._conn.execute("DELETE FROM issues")
        self._conn.commit()
        return {"issues": issue_count, "runs": run_count}

    def requeue_failed(
        self,
        numbers: Sequence[int] | None = None,
        *,
        target_stage: str = "spec_ready",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Move failed issues back to an actionable stage without wiping state."""
        if target_stage not in ACTIONABLE_STAGES:
            raise ValueError(f"target_stage must be actionable: {target_stage}")

        params: list[Any] = []
        where = "stage = 'failed'"
        if numbers:
            issue_numbers = [int(number) for number in numbers]
            where += f" AND number IN ({','.join('?' for _ in issue_numbers)})"
            params.extend(issue_numbers)

        rows = self._conn.execute(
            f"SELECT number FROM issues WHERE {where} ORDER BY number",
            params,
        ).fetchall()
        affected_numbers = [int(row["number"]) for row in rows]
        requeued = 0
        if affected_numbers:
            placeholders = ",".join("?" for _ in affected_numbers)
            cursor = self._conn.execute(
                f"""
                UPDATE issues
                   SET stage = ?, attempts = 0, last_error = NULL, updated_at = ?
                 WHERE stage = 'failed'
                   AND number IN ({placeholders})
                """,
                (target_stage, _iso(_dt(now)), *affected_numbers),
            )
            requeued = int(cursor.rowcount)
        self._conn.commit()
        return {
            "requeued": requeued,
            "numbers": affected_numbers,
            "target_stage": target_stage,
        }

    def bump_attempt(
        self,
        number: int,
        error: str,
        *,
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> IssueRecord:
        issue = self.get_issue(number)
        attempts = issue.attempts + 1
        stage = "failed" if attempts >= max_attempts else issue.stage
        self._conn.execute(
            """
            UPDATE issues
               SET attempts = ?, last_error = ?, stage = ?, updated_at = ?
             WHERE number = ?
            """,
            (attempts, error, stage, _iso(_dt(now)), number),
        )
        self._conn.commit()
        return self.get_issue(number)

    # --- control-loop module state (JSON-doc rows) ----------------------------

    def load_control_state(self, key: str) -> dict[str, Any] | None:
        """Return the persisted state dict for a control-loop module, or None
        when nothing has been written yet. Closes the supervisor
        ``previous_state not loaded`` gap: the next cycle reads its prior copy."""
        row = self._conn.execute(
            "SELECT doc FROM control_loop_state WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["doc"]))

    def control_state_fingerprint(self, key: str) -> str | None:
        """The stored material fingerprint for a module, or None if unset."""
        row = self._conn.execute(
            "SELECT fingerprint FROM control_loop_state WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row["fingerprint"])

    def save_control_state(
        self,
        key: str,
        doc: dict[str, Any],
        *,
        fingerprint: str,
        now: datetime | None = None,
    ) -> bool:
        """Upsert a module's state dict, DEDUPED on the material fingerprint:
        when the stored fingerprint already equals ``fingerprint`` (and is
        non-empty) nothing is written and False is returned (anti
        PR-per-run pile-up — the strategy-audit / supervisor material gate).
        Otherwise the doc is persisted and True is returned. Persistence is
        box-internal state (not a forge write), so it happens regardless of
        shadow/live — the caller still pre-gates on the planner's
        ``material_changed`` sentinel."""
        existing = self.control_state_fingerprint(key)
        if fingerprint and existing == fingerprint:
            return False
        self._conn.execute(
            """
            INSERT INTO control_loop_state (key, fingerprint, doc, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              fingerprint=excluded.fingerprint,
              doc=excluded.doc,
              updated_at=excluded.updated_at
            """,
            (key, fingerprint, json.dumps(doc, sort_keys=True), _iso(_dt(now))),
        )
        self._conn.commit()
        return True


class _MappingCursor:
    """Wraps a libsql cursor so fetchone/fetchall return name-accessible dict
    rows (libsql yields plain tuples); column names come from .description."""

    def __init__(self, cursor: Any):
        self._cur = cursor
        self._cols = [d[0] for d in (cursor.description or [])]

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cur.fetchone()
        return None if row is None else dict(zip(self._cols, row))

    def fetchall(self) -> list[dict[str, Any]]:
        return [dict(zip(self._cols, row)) for row in self._cur.fetchall()]

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._cur.lastrowid


class _LibsqlConn:
    """Adapts a libsql connection to the sqlite3-with-Row interface StateStore
    expects: execute() returns mapping rows; executescript() splits statements
    (libsql has no executescript)."""

    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: Iterable[Any] = ()) -> _MappingCursor:
        return _MappingCursor(self._conn.execute(sql, tuple(params)))

    def executescript(self, script: str) -> None:
        native = getattr(self._conn, "executescript", None)
        if callable(native):
            native(script)
            return
        for statement in script.split(";"):
            stmt = statement.strip()
            if stmt:
                self._conn.execute(stmt)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _load_migrations() -> list[tuple[str, str]]:
    """Return (version, sql) for every migration, sorted by filename. version is
    the leading numeric prefix; sql is the `-- +migrate Up` body (or whole file
    if no marker)."""
    out: list[tuple[str, str]] = []
    mig_dir = resources.files("wgmesh_pipeline.state").joinpath("migrations")
    names = sorted(p.name for p in mig_dir.iterdir() if p.name.endswith(".sql"))
    for name in names:
        version = name.split("_", 1)[0]
        text = mig_dir.joinpath(name).read_text()
        out.append((version, _up_section(text)))
    return out


def _up_section(text: str) -> str:
    if "-- +migrate Up" not in text:
        return text
    body = text.split("-- +migrate Up", 1)[1]
    # Stop at a Down marker if present (forward-only runner ignores Down).
    return body.split("-- +migrate Down", 1)[0]


def open_state_store(config: Any) -> "StateStore":
    """Factory honoring an EXPLICIT database mode — no silent fallback (the
    mailservice lesson). local -> file SQLite; turso -> remote libsql. Both run
    the same migrations."""
    mode = getattr(config, "database_mode", "local")
    if mode == "turso":
        return StateStore(connection=_open_turso(config))
    if mode == "local":
        return StateStore(config.database_path)
    raise ValueError(f"unknown database_mode: {mode!r} (expected 'local' or 'turso')")


def _open_turso(config: Any) -> Any:
    url = getattr(config, "turso_url", None)
    token = getattr(config, "turso_auth_token", None)
    if not url:
        raise ValueError("DATABASE_MODE=turso requires TURSO_DATABASE_URL")
    try:
        import libsql  # type: ignore
    except ImportError as exc:  # fail-loud, never silently fall back to local
        raise RuntimeError(
            "DATABASE_MODE=turso but the libsql client is not installed "
            "(pip install 'wgmesh-pipeline[turso]'  # installs libsql)"
        ) from exc
    # Pure remote over-the-wire: database is the libsql:// URL, every query hits
    # the cloud primary — durable state that survives a box rebuild (no local
    # file to lose). auth_token is the Turso database/group token.
    return libsql.connect(database=url, auth_token=token or "")


def _cooldown(attempts: int) -> timedelta:
    if attempts <= 0:
        return timedelta(seconds=0)
    return timedelta(minutes=2 ** (attempts - 1))


def _issue(row: sqlite3.Row) -> IssueRecord:
    return IssueRecord(
        number=int(row["number"]),
        title=str(row["title"]),
        classification=row["classification"],
        stage=str(row["stage"]),
        status=str(row["status"]),
        risk_tier=row["risk_tier"],
        attempts=int(row["attempts"]),
        spec_pr=row["spec_pr"],
        impl_pr=row["impl_pr"],
        last_error=row["last_error"],
        updated_at=_parse(str(row["updated_at"])),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: datetime | None) -> datetime:
    if value is None:
        return _now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _dt(value).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
