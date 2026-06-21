from __future__ import annotations

from typing import Any

import pytest

from wgmesh_pipeline.config import CI_GUARDS_CONTEXT, Config
from wgmesh_pipeline.github.client import DryRunResult, GitHubClient


class Response:
    def __init__(self, data: Any = None) -> None:
        self._data = data
        self.text = "" if data is None else "json"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._data


class Session:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self.response


def cfg(mode: str = "live") -> Config:
    return Config(
        target_repo="atvirokodosprendimai/wgmesh", mode=mode, wgmesh_bot_pat="pat"
    )


def test_create_commit_status_posts_to_statuses_endpoint() -> None:
    session = Session(Response({}))
    client = GitHubClient(cfg(), session=session)

    client.create_commit_status(
        "abc123", context=CI_GUARDS_CONTEXT, state="success", description="all green"
    )

    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/repos/atvirokodosprendimai/wgmesh/statuses/abc123")
    assert call["kwargs"]["json"]["state"] == "success"
    assert call["kwargs"]["json"]["context"] == "ci/guards"


def test_create_commit_status_failure_state_carries_description() -> None:
    session = Session(Response({}))
    client = GitHubClient(cfg(), session=session)

    client.create_commit_status(
        "abc", context=CI_GUARDS_CONTEXT, state="failure", description="blocked: pii"
    )

    payload = session.calls[0]["kwargs"]["json"]
    assert payload["state"] == "failure"
    assert payload["description"] == "blocked: pii"


def test_create_commit_status_shadow_dry_runs_with_no_network() -> None:
    session = Session(Response({}))
    client = GitHubClient(cfg(mode="shadow"), session=session)

    result = client.create_commit_status("abc", context=CI_GUARDS_CONTEXT, state="success")

    assert isinstance(result, DryRunResult)
    assert session.calls == []


def test_create_commit_status_spec_only_is_blocked() -> None:
    session = Session(Response({}))
    client = GitHubClient(cfg(mode="spec-only"), session=session)

    with pytest.raises(PermissionError):
        client.create_commit_status("abc", context=CI_GUARDS_CONTEXT, state="success")

    assert session.calls == []
