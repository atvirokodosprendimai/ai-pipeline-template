from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Iterable


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"triaged", "escalated", "failed"},
    "triaged": {"specced", "escalated", "failed"},
    "specced": {"spec_ready", "spec_opened", "escalated", "failed"},
    "spec_ready": {"implemented", "escalated", "failed"},
    "implemented": {"reviewed", "escalated", "failed"},
    "reviewed": {"merged", "escalated", "failed"},
    "spec_opened": set(),
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
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self.apply_schema()

    def close(self) -> None:
        self._conn.close()

    def apply_schema(self) -> None:
        schema = resources.files("wgmesh_pipeline.state").joinpath("schema.sql").read_text()
        self._conn.executescript(schema)
        self._conn.commit()

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

    def claim_next(self, *, now: datetime | None = None) -> IssueRecord | None:
        current = _dt(now)
        rows = self._conn.execute(
            f"""
            SELECT * FROM issues
             WHERE status = 'open'
               AND stage IN ({",".join("?" for _ in ACTIONABLE_STAGES)})
             ORDER BY updated_at ASC, number ASC
            """,
            ACTIONABLE_STAGES,
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
