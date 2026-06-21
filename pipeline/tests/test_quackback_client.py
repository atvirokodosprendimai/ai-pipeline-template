"""QuackbackClient: fail-closed raw-HTTP REST against the confirmed /api/v1 shapes.

A fake ``http_caller`` records every request and returns canned responses, so no
test touches the network. Covers: post creation returns the id; fail-closed on a
200-but-malformed payload; missing creds at construction; duplicate JSON keys;
the PATCH status body shape; and the list-by-slug query.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from wgmesh_pipeline.forge.quackback_client import (
    HttpResponse,
    QuackbackClient,
    QuackbackError,
)


@dataclass
class _Config:
    quackback_url: str | None = "https://qb.example.com"
    quackback_token: str | None = "qb_token"


class FakeHttp:
    """Records requests; returns queued responses keyed by (method, path-fragment)."""

    def __init__(self, routes: list[tuple[str, str, HttpResponse]]):
        self.routes = list(routes)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResponse:
        parsed = json.loads(body.decode("utf-8")) if body else None
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "body": parsed}
        )
        for route_method, fragment, response in self.routes:
            if route_method == method and fragment in url:
                return response
        raise AssertionError(f"unexpected request: {method} {url}")


def _client(
    routes: list[tuple[str, str, HttpResponse]],
) -> tuple[QuackbackClient, FakeHttp]:
    http = FakeHttp(routes)
    return QuackbackClient(_Config(), http_caller=http), http


# --------------------------------------------------------------- construction


def test_missing_url_raises_at_construction() -> None:
    with pytest.raises(QuackbackError, match="QUACKBACK_URL"):
        QuackbackClient(_Config(quackback_url=None), http_caller=lambda *a: None)


def test_missing_token_raises_at_construction() -> None:
    with pytest.raises(QuackbackError, match="QUACKBACK_TOKEN"):
        QuackbackClient(_Config(quackback_token=None), http_caller=lambda *a: None)


# ------------------------------------------------------------------ create


def test_create_post_returns_post_object_with_id() -> None:
    body = json.dumps({"data": {"id": "post_abc", "title": "t"}})
    client, http = _client([("POST", "/api/v1/posts", HttpResponse(201, body))])

    post = client.create_post("board_1", "t", "content", status_id="status_open")

    assert post["id"] == "post_abc"
    sent = http.calls[0]
    assert sent["body"] == {
        "boardId": "board_1",
        "title": "t",
        "content": "content",
        "statusId": "status_open",
    }
    assert sent["headers"]["Authorization"] == "Bearer qb_token"
    assert sent["headers"]["User-Agent"].startswith("Mozilla/5.0")


def test_create_post_omits_status_id_when_none() -> None:
    body = json.dumps({"data": {"id": "post_abc"}})
    client, http = _client([("POST", "/posts", HttpResponse(201, body))])

    client.create_post("board_1", "t", "c")

    assert "statusId" not in http.calls[0]["body"]


# -------------------------------------------------------------- fail-closed


def test_http_200_but_malformed_payload_raises() -> None:
    # 200 OK but no 'data' object — must NOT be trusted on status alone.
    client, _ = _client(
        [("GET", "/posts/post_x", HttpResponse(200, json.dumps({"ok": True})))]
    )

    with pytest.raises(QuackbackError, match="missing 'data' object"):
        client.get_post("post_x")


def test_non_2xx_raises() -> None:
    client, _ = _client([("GET", "/posts/post_x", HttpResponse(500, "boom"))])

    with pytest.raises(QuackbackError, match="returned 500"):
        client.get_post("post_x")


def test_duplicate_json_key_raises() -> None:
    # A self-overriding payload must be unparseable, never last-wins.
    dup = '{"data": {"id": "a"}, "data": {"id": "b"}}'
    client, _ = _client([("GET", "/posts/post_x", HttpResponse(200, dup))])

    with pytest.raises(QuackbackError, match="duplicate key"):
        client.get_post("post_x")


# ------------------------------------------------------------- set status


def test_set_post_status_patches_with_status_id_body() -> None:
    body = json.dumps({"data": {"id": "post_x", "statusId": "status_building"}})
    client, http = _client([("PATCH", "/posts/post_x", HttpResponse(200, body))])

    client.set_post_status("post_x", "status_building")

    sent = http.calls[0]
    assert sent["method"] == "PATCH"
    assert sent["body"] == {"statusId": "status_building"}


# --------------------------------------------------------------- list posts


def test_list_posts_builds_status_slug_query() -> None:
    body = json.dumps(
        {
            "data": [{"id": "post_1"}],
            "meta": {"pagination": {"cursor": "c", "hasMore": False}},
        }
    )
    client, http = _client([("GET", "/posts", HttpResponse(200, body))])

    page = client.list_posts(status_slug="accepted-for-build", limit=50)

    assert [p["id"] for p in page["data"]] == ["post_1"]
    assert "status=accepted-for-build" in http.calls[0]["url"]
    assert "limit=50" in http.calls[0]["url"]


def test_list_posts_caps_limit_at_100() -> None:
    body = json.dumps({"data": [], "meta": {}})
    client, http = _client([("GET", "/posts", HttpResponse(200, body))])

    client.list_posts(limit=500)

    assert "limit=100" in http.calls[0]["url"]


def test_list_posts_malformed_data_raises() -> None:
    client, _ = _client(
        [("GET", "/posts", HttpResponse(200, json.dumps({"data": "nope"})))]
    )

    with pytest.raises(QuackbackError, match="missing 'data' array"):
        client.list_posts()


# --------------------------------------------------------------- statuses


def test_list_statuses_returns_data_array() -> None:
    body = json.dumps(
        {"data": [{"id": "status_1", "name": "Building", "slug": "building"}]}
    )
    client, _ = _client([("GET", "/statuses", HttpResponse(200, body))])

    statuses = client.list_statuses()

    assert statuses[0]["name"] == "Building"


# --------------------------------------------------------------- comment / delete


def test_comment_posts_content_body() -> None:
    client, http = _client(
        [
            (
                "POST",
                "/posts/post_x/comments",
                HttpResponse(201, json.dumps({"data": {"id": "c1"}})),
            )
        ]
    )

    client.comment("post_x", "hello")

    assert http.calls[0]["body"] == {"content": "hello"}


def test_delete_post_tolerates_204_empty_body() -> None:
    client, http = _client([("DELETE", "/posts/post_x", HttpResponse(204, ""))])

    client.delete_post("post_x")

    assert http.calls[0]["method"] == "DELETE"
