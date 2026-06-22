"""U2 — GitHubClient.list_open_pull_requests accessor tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from wgmesh_pipeline.github.client import GitHubClient


def _client(pages: list[list[dict[str, Any]]]) -> GitHubClient:
    """Return a GitHubClient whose _request returns successive pages of PRs.

    Each call to GET /repos/o/r/pulls returns the next list in ``pages``.
    """
    cfg = SimpleNamespace(owner="o", repo="r")
    client = GitHubClient.__new__(GitHubClient)
    client.config = cfg  # type: ignore[attr-defined]
    call_count = [0]

    def fake_request(method: str, path: str, *, params: dict | None = None, **_: Any) -> object:
        assert path == "/repos/o/r/pulls"
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(pages):
            return pages[idx]
        return []

    client._request = fake_request  # type: ignore[assignment]
    return client


def test_single_page_returns_all_prs() -> None:
    raw = [
        {"number": 1, "head": {"ref": "bot/impl-1"}},
        {"number": 2, "head": {"ref": "fix/human"}},
    ]
    c = _client([raw])
    result = c.list_open_pull_requests()
    assert len(result) == 2
    assert result[0] == {"number": 1, "headRefName": "bot/impl-1"}
    assert result[1] == {"number": 2, "headRefName": "fix/human"}


def test_empty_repo_returns_empty_list() -> None:
    c = _client([[]])
    assert c.list_open_pull_requests() == []


def test_pagination_collects_across_pages() -> None:
    page1 = [{"number": i, "head": {"ref": f"bot/impl-{i}"}} for i in range(1, 4)]
    page2 = [{"number": i, "head": {"ref": f"bot/impl-{i}"}} for i in range(4, 6)]
    # page1 has 3 items (< per_page=3 triggers stop after page2 ends)
    c = _client([page1, page2, []])
    result = c.list_open_pull_requests(per_page=3)
    numbers = [r["number"] for r in result]
    assert numbers == [1, 2, 3, 4, 5]


def test_max_prs_cap_is_respected() -> None:
    big_page = [{"number": i, "head": {"ref": f"bot/{i}"}} for i in range(1, 101)]
    c = _client([big_page, big_page, big_page])
    result = c.list_open_pull_requests(per_page=100, max_prs=50)
    assert len(result) == 50


def test_missing_head_ref_returns_empty_string() -> None:
    raw = [{"number": 99, "head": {}}]
    c = _client([raw])
    result = c.list_open_pull_requests()
    assert result[0]["headRefName"] == ""
