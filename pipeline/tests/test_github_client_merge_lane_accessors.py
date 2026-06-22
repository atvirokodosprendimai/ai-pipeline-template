"""U1 — GitHubClient merge-lane-heal accessors: compare_behind_by + pr_has_failing_check."""

from __future__ import annotations

from types import SimpleNamespace

import requests

from wgmesh_pipeline.github.client import GitHubClient


def _client(routes: dict[str, object]) -> GitHubClient:
    """A client whose _request returns canned bodies keyed by path. A path
    mapped to an HTTPError(status) raises it (404 paths exercise the guards)."""
    cfg = SimpleNamespace(owner="o", repo="r")
    client = GitHubClient.__new__(GitHubClient)
    client.config = cfg  # type: ignore[attr-defined]

    def fake_request(method: str, path: str, **_: object) -> object:
        body = routes[path]
        if isinstance(body, requests.HTTPError):
            raise body
        return body

    client._request = fake_request  # type: ignore[assignment]
    return client


def _http_error(status: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(response=resp)


# compare_behind_by ------------------------------------------------------------

def test_behind_by_returns_count() -> None:
    c = _client({"/repos/o/r/compare/main...bot/impl-7": {"behind_by": 3}})
    assert c.compare_behind_by("bot/impl-7") == 3


def test_behind_by_zero_when_current() -> None:
    c = _client({"/repos/o/r/compare/main...bot/impl-7": {"behind_by": 0}})
    assert c.compare_behind_by("bot/impl-7") == 0


def test_behind_by_404_deleted_branch_is_zero() -> None:
    c = _client({"/repos/o/r/compare/main...bot/gone": _http_error(404)})
    assert c.compare_behind_by("bot/gone") == 0


def test_behind_by_missing_field_is_zero() -> None:
    c = _client({"/repos/o/r/compare/main...bot/impl-7": {"status": "ahead"}})
    assert c.compare_behind_by("bot/impl-7") == 0


def test_behind_by_non_404_error_propagates() -> None:
    c = _client({"/repos/o/r/compare/main...bot/impl-7": _http_error(500)})
    try:
        c.compare_behind_by("bot/impl-7")
        raise AssertionError("expected HTTPError to propagate")
    except requests.HTTPError:
        pass


# pr_has_failing_check ---------------------------------------------------------

def test_failing_check_run_is_detected() -> None:
    c = _client({
        "/repos/o/r/pulls/7": {"head": {"sha": "abc"}},
        "/repos/o/r/commits/abc/check-runs": {
            "check_runs": [
                {"name": "Analyze", "conclusion": "SUCCESS"},
                {"name": "build-test", "conclusion": "FAILURE"},
            ]
        },
    })
    assert c.pr_has_failing_check(7) is True


def test_all_green_check_runs_no_status_failure_is_false() -> None:
    c = _client({
        "/repos/o/r/pulls/7": {"head": {"sha": "abc"}},
        "/repos/o/r/commits/abc/check-runs": {
            "check_runs": [{"name": "build-test", "conclusion": "SUCCESS"}]
        },
        "/repos/o/r/commits/abc/status": {"statuses": []},
    })
    assert c.pr_has_failing_check(7) is False


def test_legacy_commit_status_failure_is_detected() -> None:
    c = _client({
        "/repos/o/r/pulls/7": {"head": {"sha": "abc"}},
        "/repos/o/r/commits/abc/check-runs": {"check_runs": []},
        "/repos/o/r/commits/abc/status": {
            "statuses": [{"context": "ci/legacy", "state": "failure"}]
        },
    })
    assert c.pr_has_failing_check(7) is True


def test_no_head_sha_is_false() -> None:
    c = _client({"/repos/o/r/pulls/7": {"head": {}}})
    assert c.pr_has_failing_check(7) is False
