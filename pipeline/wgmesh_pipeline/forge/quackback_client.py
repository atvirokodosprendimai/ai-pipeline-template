"""Fail-closed REST client for a self-hosted Quackback board (``/api/v1``).

Mirrors the raw-HTTP, fail-closed discipline of ``pipeline/evals/impl_judge.py``
(KTD7):

  - raw ``urllib`` with a browser-like ``User-Agent`` (Cloudflare-1010 guard);
  - ``QUACKBACK_*`` creds resolved off ``config`` (raise at construction if
    either url or token is missing — selecting Quackback without creds must
    fail loudly, never silently no-op);
  - an injectable ``http_caller`` so tests never touch the network;
  - JSON parsed with an ``object_pairs_hook`` that rejects duplicate keys (a
    self-overriding payload is unparseable → raise, never last-wins);
  - response **shape** is asserted (e.g. ``data`` present), never trusted on a
    bare HTTP 200.

Endpoints (confirmed against the live instance):

  POST   /posts                  {"boardId","title","content","statusId"?} -> 201 {"data":{post}}
  GET    /posts/{postId}                                                    -> 200 {"data":{post}}
  GET    /posts?status=<slug>&cursor=&limit=                                -> 200 {"data":[...],"meta":{...}}
  PATCH  /posts/{postId}         {"statusId":"<status TypeID>"}             -> 200
  POST   /posts/{postId}/comments{"content":"…"}                           -> 201
  DELETE /posts/{postId}                                                    -> 204
  GET    /statuses                                                          -> 200 {"data":[{status}]}

The ``status`` query filter is by status **slug**; ``statusId`` as a query param
is ignored server-side. The PATCH body, by contrast, takes the status **id**.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

# An HTTP call: (method, url, headers, body-bytes-or-None) -> (status, body-text).
HttpCaller = Callable[[str, str, Mapping[str, str], bytes | None], "HttpResponse"]

USER_AGENT = "Mozilla/5.0 (compatible; wgmesh-quackback/1.0)"
HTTP_TIMEOUT_SECONDS = 30
LIST_LIMIT_MAX = 100


class QuackbackError(RuntimeError):
    """Raised on any non-2xx response or malformed/shape-invalid payload."""


class HttpResponse:
    """Transport-level result: a status code and a raw text body."""

    def __init__(self, status: int, text: str):
        self.status = status
        self.text = text


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """object_pairs_hook: reject duplicate keys so a self-overriding payload is
    unparseable → fail-closed, never silently last-wins (impl_judge pattern)."""
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise QuackbackError(f"duplicate key in Quackback response: {key}")
        seen[key] = value
    return seen


def _default_http_caller(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None
) -> HttpResponse:
    request = urllib.request.Request(
        url, data=body, method=method, headers=dict(headers)
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8")
            return HttpResponse(int(response.status), text)
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a body
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001 — best-effort error body only
            detail = ""
        return HttpResponse(int(exc.code), detail)


class QuackbackClient:
    """Thin, fail-closed wrapper over Quackback's ``/api/v1`` REST surface."""

    def __init__(
        self,
        config: Any,
        *,
        http_caller: HttpCaller | None = None,
    ):
        base = getattr(config, "quackback_url", None)
        token = getattr(config, "quackback_token", None)
        if not base:
            raise QuackbackError("QUACKBACK_URL is required for the Quackback forge")
        if not token:
            raise QuackbackError("QUACKBACK_TOKEN is required for the Quackback forge")
        self._base = f"{base.rstrip('/')}/api/v1"
        self._token = token
        self._http_caller = http_caller or _default_http_caller

    # ------------------------------------------------------------------ posts

    def create_post(
        self,
        board_id: str,
        title: str,
        content: str,
        status_id: str | None = None,
        tag_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "boardId": board_id,
            "title": title,
            "content": content,
        }
        if status_id is not None:
            payload["statusId"] = status_id
        # ``tagIds`` (not ``tags``) is the only attach mechanism honoured on
        # create; omit it entirely when empty so the payload stays minimal.
        if tag_ids:
            payload["tagIds"] = list(tag_ids)
        body = self._call("POST", "/posts", payload=payload)
        return self._post_from(body)

    def get_post(self, post_id: str) -> dict[str, Any]:
        body = self._call("GET", f"/posts/{urllib.parse.quote(str(post_id))}")
        return self._post_from(body)

    def list_posts(
        self,
        status_slug: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return ``{"data": [...posts], "meta": {...}}`` for one page.

        Filters by status **slug** (a ``statusId`` query param is ignored
        server-side). ``limit`` is capped at 100 by the API.
        """
        params: list[tuple[str, str]] = []
        if status_slug is not None:
            params.append(("status", status_slug))
        if cursor is not None:
            params.append(("cursor", cursor))
        if limit is not None:
            params.append(("limit", str(min(int(limit), LIST_LIMIT_MAX))))
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        body = self._call("GET", f"/posts{query}")
        data = body.get("data")
        if not isinstance(data, list):
            raise QuackbackError("Quackback list response missing 'data' array")
        meta = body.get("meta")
        return {"data": data, "meta": meta if isinstance(meta, dict) else {}}

    def set_post_status(self, post_id: str, status_id: str) -> dict[str, Any]:
        """PATCH a post's status. The body takes the status **id**, not slug."""
        body = self._call(
            "PATCH",
            f"/posts/{urllib.parse.quote(str(post_id))}",
            payload={"statusId": status_id},
        )
        return self._post_from(body)

    def comment(self, post_id: str, content: str) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/posts/{urllib.parse.quote(str(post_id))}/comments",
            payload={"content": content},
        )

    def delete_post(self, post_id: str) -> None:
        # 204 No Content — no body to shape-check.
        self._call(
            "DELETE",
            f"/posts/{urllib.parse.quote(str(post_id))}",
            expect_empty=True,
        )

    def list_statuses(self) -> list[dict[str, Any]]:
        body = self._call("GET", "/statuses")
        data = body.get("data")
        if not isinstance(data, list):
            raise QuackbackError("Quackback /statuses response missing 'data' array")
        return data

    # ------------------------------------------------------------------- tags

    def list_tags(self) -> list[dict[str, Any]]:
        body = self._call("GET", "/tags")
        data = body.get("data")
        if not isinstance(data, list):
            raise QuackbackError("Quackback /tags response missing 'data' array")
        return data

    def create_tag(self, name: str) -> dict[str, Any]:
        body = self._call("POST", "/tags", payload={"name": name})
        return self._post_from(body)

    # --------------------------------------------------------------- plumbing

    def _post_from(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Assert the ``{"data": {post}}`` shape and return the post object.

        Never trust HTTP 200 alone (KTD7): a 200 with no ``data`` object is a
        malformed response and must raise, not return an empty dict.
        """
        data = body.get("data")
        if not isinstance(data, dict) or not data:
            raise QuackbackError("Quackback response missing 'data' object")
        return data

    def _call(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        expect_empty: bool = False,
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        response = self._http_caller(method, url, headers, body)
        if not 200 <= response.status < 300:
            detail = (response.text or "")[:300]
            raise QuackbackError(
                f"Quackback {method} {path} returned {response.status}: {detail}"
            )
        if expect_empty or not (response.text or "").strip():
            return {}
        try:
            parsed = json.loads(response.text, object_pairs_hook=_no_duplicate_keys)
        except QuackbackError:
            raise
        except ValueError as exc:
            raise QuackbackError(
                f"Quackback {method} {path} returned non-JSON body"
            ) from exc
        if not isinstance(parsed, dict):
            raise QuackbackError(f"Quackback {method} {path} returned non-object JSON")
        return parsed
