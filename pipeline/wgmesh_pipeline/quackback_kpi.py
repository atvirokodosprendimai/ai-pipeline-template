"""Queue-health KPI sourced from the Quackback board (cutover U3).

Once Build Suggestions live on the Quackback board instead of GitHub Issues, the
GitHub ``issues_by_function_label`` signal goes blind. This module reconstructs
the queue-health signal from the board:

  - **posts-by-decision-status** — a count per board status (the 8 the board
    carries), so the pulse can see where work piles up.
  - **oldest-undecided age** — the age of the OLDEST post still awaiting a human
    decision (``Open for Vote`` / ``Needs Refinement``). This is the load-bearing
    silent-stall canary (KTD3): with no founder-notification in the bare cutover,
    a rising oldest-undecided age is the only visible signal that the queue has
    stalled at zero builds.

PR / merge-rate / CI / release / stars stay on GitHub (``collect-github.sh``,
unchanged) — only the ISSUE-derived queue block repoints. ``select_queue_health``
is the seam that picks the source by ``forge_kind``.

Reads are **fail-closed-loud** on the gating counts: any ``QuackbackError`` from a
status read propagates (a silent zero would read as "queue empty / all decided"
and hide a real stall). The collector performs no live calls in tests — it takes
any object exposing ``list_statuses`` / ``list_posts`` (the ``QuackbackClient``
read surface).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterator, Optional, Protocol

from wgmesh_pipeline.forge.quackback_status import UNDECIDED_STATUSES

log = logging.getLogger("wgmesh_pipeline.quackback_kpi")

_PAGE_LIMIT = 100
# Pagination backstop: a status with more pages than this is pathological; stop
# rather than loop unboundedly (mirrors the dedup-scan cap in QuackbackForge).
_MAX_PAGES = 50


class _Reader(Protocol):
    def list_statuses(self) -> list[dict[str, Any]]: ...

    def list_posts(
        self,
        status_slug: str | None = ...,
        cursor: str | None = ...,
        limit: int | None = ...,
    ) -> dict[str, Any]: ...


def _parse_ts(raw: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (``...Z`` or offset) to an aware datetime, or
    ``None`` if absent/unparseable — a missing createdAt must not crash the KPI."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_posts(client: _Reader, slug: str) -> Iterator[dict[str, Any]]:
    """Yield every post in ``slug``, following cursor pagination (board read).
    A read error propagates — the caller treats gating counts as fail-closed."""
    cursor: str | None = None
    pages = 0
    while pages < _MAX_PAGES:
        page = client.list_posts(status_slug=slug, cursor=cursor, limit=_PAGE_LIMIT)
        posts = page.get("data", [])
        for post in posts:
            yield post
        pagination = (page.get("meta") or {}).get("pagination") or {}
        cursor = pagination.get("cursor")
        pages += 1
        if not pagination.get("hasMore") or not cursor or not posts:
            break


def collect_quackback_queue_health(
    client: _Reader, *, now: datetime | None = None
) -> dict[str, Any]:
    """Build the Quackback queue-health block. Fail-closed-loud on any status read.

    Returns the same envelope the pulse/observation queue consumer expects, with
    ``posts_by_decision_status`` (name → count) and ``oldest_undecided_age_*``
    replacing the GitHub ``issues_by_function_label`` signal.
    """
    now = now or datetime.now(timezone.utc)
    statuses = client.list_statuses()

    posts_by_status: dict[str, int] = {}
    oldest_undecided: datetime | None = None

    for status in statuses:
        name = str(status.get("name") or "")
        slug = status.get("slug")
        if not slug:
            # A status with no slug can't be queried — skip it loudly rather than
            # silently zero it (the slug filter is the only count primitive).
            log.warning("Quackback status %r has no slug — skipping from KPI", name)
            continue
        count = 0
        is_undecided = name in UNDECIDED_STATUSES
        for post in _iter_posts(client, str(slug)):
            count += 1
            if is_undecided:
                ts = _parse_ts(
                    str(post.get("createdAt") or post.get("created_at") or "")
                )
                if ts is not None and (
                    oldest_undecided is None or ts < oldest_undecided
                ):
                    oldest_undecided = ts
        posts_by_status[name] = count

    if oldest_undecided is not None:
        age = (now - oldest_undecided).total_seconds()
        age_seconds: int | None = int(age)
        age_hours: float | None = round(age / 3600, 2)
    else:
        age_seconds = None
        age_hours = None

    return {
        "source": "quackback",
        "collected_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "posts_by_decision_status": posts_by_status,
        "oldest_undecided_age_seconds": age_seconds,
        "oldest_undecided_age_hours": age_hours,
    }


def select_queue_health(
    forge_kind: str | None,
    *,
    github_block: Any,
    quackback_block: Any,
) -> Any:
    """Pick the queue-health signal source by forge kind (cutover U3 repoint).

    ``quackback`` → the board block; anything else (``github``/``None``) → the
    unchanged GitHub issues-by-label block. The default is github so a missing /
    unset ``forge_kind`` never silently drops the GitHub signal.
    """
    if forge_kind == "quackback":
        return quackback_block
    return github_block
