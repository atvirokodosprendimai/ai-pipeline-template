"""U4 Quackback ingest: ``reconcile_quackback`` + store-backed post-id map.

The Quackback decision board has no GitHub-label semantics, so the GitHub
``reconcile_issues`` (label/MERGED_LABELS/resolution logic) misfires on posts
(KTD3). This module is the dedicated, idempotent ingest: it upserts only
``Accepted for Build`` posts into the store at ``queued``, keyed on a
store-backed ``(quackback_post_id, accept_marker)`` mapping.
"""

from __future__ import annotations

import asyncio

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient
from wgmesh_pipeline.github.reconcile import ReconcileResult, reconcile_quackback
from wgmesh_pipeline.poller import Poller
from wgmesh_pipeline.state.store import StateStore


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeQuackbackForge:
    """Stands in for ``QuackbackForge`` — only ``list_accepted_posts`` is used
    by the ingest. ``posts`` is the canned page of raw post dicts."""

    def __init__(self, posts: list[dict]) -> None:
        self.posts = posts
        self.calls = 0

    def list_accepted_posts(self) -> list[dict]:
        self.calls += 1
        return list(self.posts)


class ExplodingForge:
    """A forge whose ingest read fails — proves fail-closed propagation (KTD5)."""

    def list_accepted_posts(self) -> list[dict]:
        raise RuntimeError("quackback unavailable")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def store(tmp_path) -> StateStore:
    return StateStore(tmp_path / "state.db")


# --------------------------------------------------------------------------- #
# Migration
# --------------------------------------------------------------------------- #


def test_migration_0003_creates_quackback_posts_table(store: StateStore) -> None:
    # migrate() ran in __init__; 0003 must have applied.
    row = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='quackback_posts'"
    ).fetchone()
    assert row is not None and str(row["name"]) == "quackback_posts"


# --------------------------------------------------------------------------- #
# Store mapping: map_quackback_post / quackback_post_id_for
# --------------------------------------------------------------------------- #


def test_map_unknown_post_inserts_and_is_fresh(store: StateStore) -> None:
    number, fresh = store.map_quackback_post("post_01", "2026-06-21T00:00:00Z")
    assert isinstance(number, int)
    assert fresh is True
    # Reverse lookup resolves the same id.
    assert store.quackback_post_id_for(number) == "post_01"


def test_map_same_post_same_marker_is_idempotent(store: StateStore) -> None:
    n1, f1 = store.map_quackback_post("post_01", "m1")
    n2, f2 = store.map_quackback_post("post_01", "m1")
    assert n1 == n2
    assert f1 is True
    assert f2 is False  # already ingested at this marker


def test_map_same_post_changed_marker_is_fresh_again_same_number(
    store: StateStore,
) -> None:
    n1, f1 = store.map_quackback_post("post_01", "m1")
    n2, f2 = store.map_quackback_post("post_01", "m2")
    assert f1 is True
    assert f2 is True  # re-accept after cancel → a new run is allowed
    assert n1 == n2  # same number reused to re-queue


def test_distinct_posts_get_distinct_numbers(store: StateStore) -> None:
    n1, _ = store.map_quackback_post("post_01", "m1")
    n2, _ = store.map_quackback_post("post_02", "m1")
    assert n1 != n2


def test_quackback_post_id_for_unknown_number_is_none(store: StateStore) -> None:
    assert store.quackback_post_id_for(999) is None


# --------------------------------------------------------------------------- #
# reconcile_quackback
# --------------------------------------------------------------------------- #


def _post(post_id: str, title: str, updated_at: str) -> dict:
    return {"id": post_id, "title": title, "updatedAt": updated_at}


def test_happy_one_accepted_post_queued_once(store: StateStore) -> None:
    forge = FakeQuackbackForge([_post("post_01", "Add SSO", "2026-06-21T00:00:00Z")])

    result = reconcile_quackback(forge, store)

    assert isinstance(result, ReconcileResult)
    assert result.seen == 1
    assert result.queued == 1
    assert result.escalated == 0
    assert result.merged == 0

    records = store.list_issues()
    assert len(records) == 1
    record = records[0]
    assert record.stage == "queued"
    assert record.status == "open"
    assert record.title == "Add SSO"

    # The mapped int threads cleanly into a bot/impl-{n} branch name (KTD6).
    n = record.number
    assert isinstance(n, int)
    branch = f"bot/impl-{n}"
    assert branch == f"bot/impl-{n}"
    assert branch.rsplit("-", 1)[1] == str(n)


def test_reconcile_carries_post_body_as_brief(store: StateStore) -> None:
    # The PM brief in the post body must reach the builder (not title-only).
    brief = "## Problem\nTrial drop-off.\n## Acceptance Criteria\n- lead form\n"
    post = {
        "id": "post_01",
        "title": "Add SSO",
        "updatedAt": "2026-06-21T00:00:00Z",
        "content": brief,
    }
    reconcile_quackback(FakeQuackbackForge([post]), store)

    record = store.list_issues()[0]
    assert record.body == brief


def test_reconcile_drops_body_that_fails_sanitise(
    store: StateStore, monkeypatch
) -> None:
    # A body that fails the sanitise wall degrades to empty (build from title),
    # never leaks into a public spec — the issue is still queued.
    monkeypatch.setattr(
        "wgmesh_pipeline.graph.nodes.review.run_sanitise", lambda _t: False
    )
    post = {
        "id": "post_01",
        "title": "Add SSO",
        "updatedAt": "2026-06-21T00:00:00Z",
        "content": "leaks a secret",
    }
    result = reconcile_quackback(FakeQuackbackForge([post]), store)

    assert result.queued == 1  # still queued (title is safe)
    assert store.list_issues()[0].body == ""  # unsafe brief dropped


def test_migration_0004_adds_issue_body_column(store: StateStore) -> None:
    cols = {
        str(r["name"])
        for r in store._conn.execute("PRAGMA table_info(issues)").fetchall()
    }
    assert "body" in cols


def test_idempotent_same_post_twice_one_row_second_queued_zero(
    store: StateStore,
) -> None:
    forge = FakeQuackbackForge([_post("post_01", "Add SSO", "2026-06-21T00:00:00Z")])

    first = reconcile_quackback(forge, store)
    second = reconcile_quackback(forge, store)

    assert first.queued == 1
    assert second.queued == 0  # already ingested; idempotent
    assert second.seen == 1
    assert len(store.list_issues()) == 1


def test_reaccept_changed_updatedat_requeues_same_number(store: StateStore) -> None:
    forge = FakeQuackbackForge([_post("post_01", "Add SSO", "2026-06-21T00:00:00Z")])
    first = reconcile_quackback(forge, store)
    n_first = store.list_issues()[0].number

    # Founder cancelled then re-accepted → updatedAt advanced.
    forge.posts = [_post("post_01", "Add SSO", "2026-06-22T09:00:00Z")]
    second = reconcile_quackback(forge, store)

    assert first.queued == 1
    assert second.queued == 1  # a new run is allowed
    records = store.list_issues()
    assert len(records) == 1  # same row reused
    assert records[0].number == n_first
    assert records[0].stage == "queued"


def test_non_integer_post_id_gets_stable_int_reused_across_polls(
    store: StateStore,
) -> None:
    pid = "post_01h9xyzABCDEF0123456789"
    forge = FakeQuackbackForge([_post(pid, "Opaque id", "2026-06-21T00:00:00Z")])

    reconcile_quackback(forge, store)
    n1 = store.list_issues()[0].number
    reconcile_quackback(forge, store)
    n2 = store.list_issues()[0].number

    assert isinstance(n1, int)
    assert n1 == n2  # stable across polls
    assert store.quackback_post_id_for(n1) == pid


def test_fail_closed_propagates_api_error(store: StateStore) -> None:
    forge = ExplodingForge()
    with pytest.raises(RuntimeError, match="quackback unavailable"):
        reconcile_quackback(forge, store)
    # Nothing ingested on failure — never an empty-looks-healthy result.
    assert store.list_issues() == []


def test_falsy_post_id_is_skipped(store: StateStore) -> None:
    forge = FakeQuackbackForge(
        [
            {"id": "", "title": "no id", "updatedAt": "m1"},
            _post("post_02", "real", "m1"),
        ]
    )

    result = reconcile_quackback(forge, store)

    assert result.seen == 1  # only the real post is counted
    assert result.queued == 1
    records = store.list_issues()
    assert len(records) == 1
    assert records[0].title == "real"


# --------------------------------------------------------------------------- #
# poller.tick branch: forge_kind == "quackback" routes to reconcile_quackback
# --------------------------------------------------------------------------- #


class _SpyGraph:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def triage(self, state):
        self.calls.append("triage")
        return {**state, "classification": "fix"}

    def spec(self, state):
        self.calls.append("spec")
        return {**state, "spec_path": "specs/issue.md"}


def test_tick_uses_reconcile_quackback_for_quackback_forge_kind(
    tmp_path, monkeypatch
) -> None:
    cfg = Config(
        target_repo="atvirokodosprendimai/wgmesh",
        mode="shadow",
        max_files=3,
        forge_kind="quackback",
    )
    store = StateStore(tmp_path / "state.db")

    fired: list[str] = []

    def spy_issues(client, store, **kwargs):
        fired.append("issues")
        return ReconcileResult(seen=0, queued=0, escalated=0, merged=0)

    def spy_quackback(client, store):
        fired.append("quackback")
        return ReconcileResult(seen=0, queued=0, escalated=0, merged=0)

    monkeypatch.setattr("wgmesh_pipeline.poller.reconcile_issues", spy_issues)
    monkeypatch.setattr("wgmesh_pipeline.poller.reconcile_quackback", spy_quackback)

    p = Poller(
        config=cfg,
        store=store,
        client=FakeQuackbackForge([]),
        graph=_SpyGraph(),
    )

    asyncio.run(p.tick())

    assert fired == ["quackback"]  # quackback branch fired, github did not


def test_tick_uses_reconcile_issues_for_github_forge_kind(
    tmp_path, monkeypatch
) -> None:
    cfg = Config(
        target_repo="atvirokodosprendimai/wgmesh",
        mode="shadow",
        max_files=3,
        forge_kind="github",
    )
    store = StateStore(tmp_path / "state.db")

    fired: list[str] = []

    def spy_issues(client, store, **kwargs):
        fired.append("issues")
        return ReconcileResult(seen=0, queued=0, escalated=0, merged=0)

    def spy_quackback(client, store):
        fired.append("quackback")
        return ReconcileResult(seen=0, queued=0, escalated=0, merged=0)

    monkeypatch.setattr("wgmesh_pipeline.poller.reconcile_issues", spy_issues)
    monkeypatch.setattr("wgmesh_pipeline.poller.reconcile_quackback", spy_quackback)

    p = Poller(
        config=cfg,
        store=store,
        client=GitHubClient(cfg),
        graph=_SpyGraph(),
    )

    asyncio.run(p.tick())

    assert fired == ["issues"]  # default github branch fired
