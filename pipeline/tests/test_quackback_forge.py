"""QuackbackForge: composition split + allowlist guard + sanitise wall (U2/U3).

The forge holds two backends; these tests inject fakes for each and assert the
explicit per-method split — a PR method must hit ``_gh``, an issue/post method
must hit ``_qb`` — plus the KTD9 client-side allowlist on ``set_status`` and the
sanitise wall on ``create_issue``.
"""

from __future__ import annotations

from typing import Any

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.protocol import Forge
from wgmesh_pipeline.forge.quackback import QuackbackForge


class FakeQB:
    """Records every QuackbackClient call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        # name → existing tag id; the two Build-Suggestion tags pre-exist.
        self._tags: dict[str, str] = {
            "agent-suggestion": "tag_sugg",
            "build-candidate": "tag_cand",
        }
        # Board posts returned by an unfiltered list_posts (cross-status dedup).
        self.board_posts: list[dict[str, Any]] = []

    def create_post(
        self,
        board_id: str,
        title: str,
        content: str,
        status_id: str | None = None,
        tag_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            ("create_post", (board_id, title, content, status_id, tag_ids))
        )
        return {"id": "post_new", "title": title}

    def list_tags(self) -> list[dict[str, Any]]:
        self.calls.append(("list_tags", ()))
        return [{"id": tid, "name": name} for name, tid in self._tags.items()]

    def create_tag(self, name: str) -> dict[str, Any]:
        self.calls.append(("create_tag", (name,)))
        tid = f"tag_{name.replace('-', '_')}"
        self._tags[name] = tid
        return {"id": tid, "name": name}

    def get_post(self, post_id: str) -> dict[str, Any]:
        self.calls.append(("get_post", (post_id,)))
        return {"id": post_id, "title": "T", "tags": [], "deletedAt": None}

    def comment(self, post_id: str, content: str) -> dict[str, Any]:
        self.calls.append(("comment", (post_id, content)))
        return {"id": "c1"}

    def set_post_status(self, post_id: str, status_id: str) -> dict[str, Any]:
        self.calls.append(("set_post_status", (post_id, status_id)))
        return {"id": post_id, "statusId": status_id}

    def list_posts(self, status_slug=None, cursor=None, limit=None) -> dict[str, Any]:
        self.calls.append(("list_posts", (status_slug, cursor, limit)))
        # An unfiltered list (no slug) returns the whole board for dedup; a
        # slug-filtered list keeps its existing empty-by-default behaviour.
        data = self.board_posts if status_slug is None else []
        return {"data": list(data), "meta": {}}

    def list_statuses(self) -> list[dict[str, Any]]:
        self.calls.append(("list_statuses", ()))
        return [
            {
                "id": "status_afb",
                "name": "Accepted for Build",
                "slug": "accepted-for-build",
            },
            {"id": "status_bld", "name": "Building", "slug": "building"},
            {
                "id": "status_rfr",
                "name": "Ready for Review",
                "slug": "ready-for-review",
            },
            {"id": "status_shp", "name": "Shipped", "slug": "shipped"},
        ]


class FakeGH:
    """Records every GitHubClient call (PR backend). Also provides the sanitise
    hook the forge reuses for create_issue."""

    def __init__(self, *, sanitiser=lambda _t: True) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._sanitiser = sanitiser
        self.sanitised: list[tuple[str, dict[str, Any]]] = []

    def _sanitise_write(self, operation: str, payload: dict[str, Any]) -> None:
        self.sanitised.append((operation, payload))
        for value in payload.values():
            if not self._sanitiser(str(value)):
                from wgmesh_pipeline.github.client import SanitiseError

                raise SanitiseError(f"sanitise failed for {operation}")

    def get_pr(self, number: int) -> dict[str, Any]:
        self.calls.append(("get_pr", (number,)))
        return {"number": number, "merged": True}

    def create_pr(self, *, title, head, base, body, spec_pr=False) -> dict[str, Any]:
        self.calls.append(("create_pr", (title, head, base, body, spec_pr)))
        return {"number": 99}

    def merge_pr(self, pr_number, *, commit_title=None) -> dict[str, Any]:
        self.calls.append(("merge_pr", (pr_number, commit_title)))
        return {"merged": True}

    def add_label(self, issue_number, label, *, spec_pr=False) -> dict[str, Any]:
        self.calls.append(("add_label", (issue_number, label, spec_pr)))
        return {"ok": True}


def _cfg() -> Config:
    return Config(
        target_repo="o/r",
        mode="live",
        wgmesh_bot_pat="pat",
        quackback_url="https://qb.example.com",
        quackback_token="qb_token",
    )


def _forge(
    *, gh: FakeGH | None = None, qb: FakeQB | None = None
) -> tuple[QuackbackForge, FakeGH, FakeQB]:
    gh = gh or FakeGH()
    qb = qb or FakeQB()
    forge = QuackbackForge(_cfg(), gh=gh, qb=qb, board_id="board_1")
    return forge, gh, qb


# ----------------------------------------------------------------- protocol


def test_quackback_forge_satisfies_forge_protocol() -> None:
    forge, _, _ = _forge()
    assert isinstance(forge, Forge)


# ----------------------------------------------------------------- split


def test_issue_method_routes_to_qb() -> None:
    forge, gh, qb = _forge()

    post = forge.create_issue(title="t", body="b", labels=())

    assert post["id"] == "post_new"
    # U5: create_issue reads the board (dedup) and tags (resolution) then writes
    # exactly one post — create_post is the ONLY backend WRITE on _qb, and
    # nothing reached _gh (no PR/code-backend call for an issue method).
    ops = [c[0] for c in qb.calls]
    assert ops.count("create_post") == 1
    assert "comment" not in ops
    assert gh.calls == []


def test_pr_method_routes_to_gh() -> None:
    forge, gh, qb = _forge()

    result = forge.create_pr(title="t", head="bot/impl-1", base="main", body="b")

    assert result["number"] == 99
    assert [c[0] for c in gh.calls] == ["create_pr"]
    # No post backend touched for a PR method.
    assert qb.calls == []


def test_get_pr_routes_to_gh() -> None:
    forge, gh, qb = _forge()

    forge.get_pr(42)

    assert gh.calls == [("get_pr", (42,))]
    assert qb.calls == []


def test_labels_route_to_gh() -> None:
    forge, gh, qb = _forge()

    forge.add_label(7, "needs-human")

    assert [c[0] for c in gh.calls] == ["add_label"]
    assert qb.calls == []


# --------------------------------------------------------------- set_status


def test_set_status_building_allowed_patches_via_qb() -> None:
    forge, gh, qb = _forge()
    # Register a post-id↔int mapping by creating an issue first.
    forge.create_issue(title="t", body="b")
    qb.calls.clear()

    forge.set_status(1, "Building")

    ops = [c[0] for c in qb.calls]
    assert "set_post_status" in ops
    patch = next(c for c in qb.calls if c[0] == "set_post_status")
    assert patch[1] == ("post_new", "status_bld")
    assert gh.calls == []


def test_set_status_accepted_for_build_raises_locally() -> None:
    forge, gh, qb = _forge()
    forge.create_issue(title="t", body="b")
    qb.calls.clear()

    with pytest.raises(PermissionError, match="Accepted for Build"):
        forge.set_status(1, "Accepted for Build")

    # The forbidden status never reaches the backend at all.
    assert all(c[0] != "set_post_status" for c in qb.calls)


def test_set_status_rejected_raises_locally() -> None:
    forge, _, qb = _forge()
    forge.create_issue(title="t", body="b")
    qb.calls.clear()

    with pytest.raises(PermissionError, match="Rejected"):
        forge.set_status(1, "Rejected")

    assert qb.calls == []


# --------------------------------------------------------------- sanitise wall


def test_create_issue_runs_sanitise_wall() -> None:
    forge, gh, _ = _forge()

    forge.create_issue(title="clean title", body="clean body")

    assert (
        "create_issue",
        {"title": "clean title", "body": "clean body"},
    ) in gh.sanitised


def test_create_issue_blocked_by_sanitise_failure() -> None:
    from wgmesh_pipeline.github.client import SanitiseError

    # A sanitiser that rejects a body carrying a synthetic secret.
    gh = FakeGH(sanitiser=lambda text: "SECRET" not in text)
    forge, gh, qb = _forge(gh=gh)

    with pytest.raises(SanitiseError):
        forge.create_issue(title="t", body="leaking SECRET token")

    # Blocked before the post is created.
    assert qb.calls == []


# --------------------------------------------------------------- id seam


def test_create_issue_then_get_issue_translates_int_handle() -> None:
    forge, _, qb = _forge()

    forge.create_issue(title="t", body="b")
    issue = forge.get_issue(1)

    assert issue is not None
    assert issue.number == 1
    # get_issue translated int handle 1 → the real post id on _qb.
    assert ("get_post", ("post_new",)) in qb.calls


def test_get_issue_unknown_handle_returns_none() -> None:
    forge, _, qb = _forge()

    assert forge.get_issue(999) is None


def test_list_open_issues_filters_to_accepted_for_build() -> None:
    qb = FakeQB()

    def _list(status_slug=None, cursor=None, limit=None):
        qb.calls.append(("list_posts", (status_slug, cursor, limit)))
        return {
            "data": [{"id": "post_a", "title": "A", "tags": [], "deletedAt": None}],
            "meta": {},
        }

    qb.list_posts = _list  # type: ignore[assignment]
    forge, _, qb = _forge(qb=qb)

    issues = forge.list_open_issues()

    # Queried by the Accepted-for-Build slug, mapped to a stable int.
    list_call = next(c for c in qb.calls if c[0] == "list_posts")
    assert list_call[1][0] == "accepted-for-build"
    assert len(issues) == 1
    assert issues[0].title == "A"


# ----------------------------------------------------- U5: build-suggestion tags


def test_create_issue_tags_post_with_build_suggestion_and_label_tags() -> None:
    forge, gh, qb = _forge()

    forge.create_issue(title="Add SSO login", body="b", labels=("growth",))

    create = next(c for c in qb.calls if c[0] == "create_post")
    # (board_id, title, content, status_id, tag_ids)
    board_id, title, _content, status_id, tag_ids = create[1]
    assert board_id == "board_1"
    assert title == "Add SSO login"
    # Default status: no statusId — the board's default ("Open for Vote").
    assert status_id is None
    # The two pre-existing Build-Suggestion tags plus the growth label tag.
    assert set(tag_ids) == {"tag_sugg", "tag_cand", "tag_growth"}


def test_create_issue_resolves_missing_tag_by_creating_it_once() -> None:
    forge, _, qb = _forge()

    # "growth" does not pre-exist → must be created exactly once.
    forge.create_issue(title="t1", body="b", labels=("growth",))
    forge.create_issue(title="t2 distinct", body="b", labels=("growth",))

    creations = [c for c in qb.calls if c[0] == "create_tag" and c[1] == ("growth",)]
    assert len(creations) == 1
    # The created id is reused on the second post.
    second = [c for c in qb.calls if c[0] == "create_post"][1]
    assert "tag_growth" in second[1][4]


# ----------------------------------------------------- U5: cross-status dedup


def test_create_issue_dedups_against_existing_board_post() -> None:
    qb = FakeQB()
    # A near-duplicate already on the board (any status).
    qb.board_posts = [{"id": "post_old", "title": "Add  SSO   Login!"}]
    forge, gh, qb = _forge(qb=qb)

    result = forge.create_issue(title="add sso login", body="more detail")

    # Commented on the existing post; NO new post created.
    assert ("comment", ("post_old", "more detail")) in qb.calls
    assert all(c[0] != "create_post" for c in qb.calls)
    # Returns the existing post.
    assert result["id"] == "post_old"


def test_create_issue_creates_post_when_no_duplicate() -> None:
    qb = FakeQB()
    qb.board_posts = [{"id": "post_old", "title": "Totally unrelated feature"}]
    forge, _, qb = _forge(qb=qb)

    forge.create_issue(title="Add SSO login", body="b")

    assert any(c[0] == "create_post" for c in qb.calls)
    assert all(c[0] != "comment" for c in qb.calls)


def test_dedup_sanitise_wall_runs_before_any_post() -> None:
    from wgmesh_pipeline.github.client import SanitiseError

    gh = FakeGH(sanitiser=lambda text: "SECRET" not in text)
    qb = FakeQB()
    forge, gh, qb = _forge(gh=gh, qb=qb)

    with pytest.raises(SanitiseError):
        forge.create_issue(title="t", body="leaking SECRET token")

    # Sanitise blocks before list/create/comment touch the board.
    assert qb.calls == []


# ----------------------------------------------------- U5: executor angle


def test_executor_create_issue_routes_to_quackback_build_suggestion() -> None:
    from dataclasses import dataclass

    from wgmesh_pipeline.control_loop.executor import _h_create_issue

    @dataclass
    class _Action:
        title: str
        body: str
        labels: tuple[str, ...]

    forge, gh, qb = _forge()
    action = _Action(title="Add SSO login", body="b", labels=("growth",))

    post = _h_create_issue(forge, action)

    # The executor handler produced a Quackback Build Suggestion, not a GH call.
    assert post["id"] == "post_new"
    assert any(c[0] == "create_post" for c in qb.calls)
    assert gh.calls == []
