"""Forge conformance suite: one behavioral contract, both adapters.

Each test runs against GitHubClient AND GiteaForge with HTTP stubbed at the
session level — the lowest boundary, so every write gate, sanitise hook and
endpoint shape stays in the execution path (test-fakes-override-the-gate
lesson). Per-adapter fixtures encode each host's actual response shapes;
behavioral assertions are identical across adapters. Divergences (label ids,
commit-status vs check-runs, no Search API, pull_request:null) live in the
fixtures, never in the contract.

An opt-in live class at the bottom runs key contract cases against a real
Forgejo (see docker-compose.gitea.yml); it is skipped unless GITEA_LIVE=1.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
import requests

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.gitea import GiteaForge
from wgmesh_pipeline.forge.protocol import ForgeIssue
from wgmesh_pipeline.github.client import DryRunResult, GitHubClient

GITHUB = "github"
GITEA = "gitea"
ADAPTERS = (GITHUB, GITEA)

parametrize_adapters = pytest.mark.parametrize("kind", ADAPTERS)


class Response:
    def __init__(self, data: Any = None, text: str | None = None):
        self._data = data
        self.text = text if text is not None else ("" if data is None else "json")

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._data


class ErrorResponse(Response):
    def __init__(self, status_code: int, text: str = ""):
        super().__init__(text=text)
        self.status_code = status_code

    def raise_for_status(self) -> None:
        raise requests.HTTPError(f"{self.status_code} Error", response=self)


class RoutingSession:
    """Session stub routing by (method, url fragment); unmatched requests fail
    loudly so a test can never silently hit an endpoint it did not declare."""

    def __init__(self, routes: list[tuple[str, str, Response]]):
        self.routes = list(routes)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        for route_method, fragment, response in self.routes:
            if route_method == method and fragment in url:
                return response
        raise AssertionError(f"unexpected request: {method} {url}")


def make_client(
    kind: str, mode: str, routes: list[tuple[str, str, Response]]
) -> tuple[GitHubClient, RoutingSession]:
    cfg = Config(
        target_repo="o/r",
        mode=mode,
        wgmesh_bot_pat="author-pat",
    )
    session = RoutingSession(routes)
    cls = GitHubClient if kind == GITHUB else GiteaForge
    return cls(cfg, session=session, sanitiser=lambda _text: True), session


# ---------------------------------------------------------------------------
# list_open_issues: host PR objects must be filtered
# ---------------------------------------------------------------------------


def _issues_payload(kind: str) -> list[dict[str, Any]]:
    real: dict[str, Any] = {
        "number": 10,
        "title": "Real issue",
        "labels": [],
        "state": "open",
    }
    pr: dict[str, Any] = {
        "number": 667,
        "title": "spec: Issue #652 - recursion bait",
        "labels": [],
        "state": "open",
    }
    if kind == GITHUB:
        # GitHub: plain issues OMIT the key; PRs carry it populated.
        pr["pull_request"] = {"url": "https://api.github.com/repos/o/r/pulls/667"}
    else:
        # Gitea: plain issues carry "pull_request": null; PRs carry an object.
        real["pull_request"] = None
        pr["pull_request"] = {"merged": False, "merged_at": None}
    return [real, pr]


@parametrize_adapters
def test_list_open_issues_filters_host_pr_objects(kind: str) -> None:
    client, _ = make_client(
        kind, "shadow", [("GET", "/issues", Response(_issues_payload(kind)))]
    )

    issues = client.list_open_issues()

    assert [issue.number for issue in issues] == [10]
    assert isinstance(issues[0], ForgeIssue)


@parametrize_adapters
def test_list_needs_triage_requests_label_filter(kind: str) -> None:
    # Contract: server-side needs-triage label filter on both hosts. Both
    # adapters also filter pull_request objects in BOTH listing methods (the
    # bug #11 guard; GitHubClient gained the list_needs_triage filter after
    # this suite first caught the asymmetry).
    payload = [item for item in _issues_payload(kind) if not item.get("pull_request")]
    client, session = make_client(
        kind, "shadow", [("GET", "/issues", Response(payload))]
    )

    issues = client.list_needs_triage()

    assert [issue.number for issue in issues] == [10]
    assert session.calls[0]["kwargs"]["params"]["labels"] == "needs-triage"


def test_gitea_list_needs_triage_filters_pr_objects() -> None:
    client, _ = make_client(
        GITEA, "shadow", [("GET", "/issues", Response(_issues_payload(GITEA)))]
    )

    assert [issue.number for issue in client.list_needs_triage()] == [10]


# ---------------------------------------------------------------------------
# get_issue: direct read with state, missing issues, and PR filtering
# ---------------------------------------------------------------------------


def _issue_payload(
    kind: str, *, number: int = 10, state: str = "open"
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "number": number,
        "title": "Direct issue",
        "labels": [{"name": "needs-human"}],
        "state": state,
    }
    if kind == GITEA:
        payload["pull_request"] = None
    return payload


@parametrize_adapters
def test_get_issue_returns_direct_issue_with_state(kind: str) -> None:
    client, _ = make_client(
        kind,
        "shadow",
        [("GET", "/issues/10", Response(_issue_payload(kind, state="closed")))],
    )

    got = client.get_issue(10)

    assert got is not None
    assert got.number == 10
    assert got.state == "closed"
    assert got.labels == ("needs-human",)


@parametrize_adapters
def test_get_issue_returns_none_on_missing_issue(kind: str) -> None:
    client, _ = make_client(
        kind, "shadow", [("GET", "/issues/404", ErrorResponse(404, "not found"))]
    )

    assert client.get_issue(404) is None


@parametrize_adapters
def test_get_issue_returns_none_for_host_pr_object(kind: str) -> None:
    payload = _issue_payload(kind, number=667)
    payload["pull_request"] = {"url": "https://forge.example/o/r/pulls/667"}
    client, _ = make_client(kind, "shadow", [("GET", "/issues/667", Response(payload))])

    assert client.get_issue(667) is None


# ---------------------------------------------------------------------------
# find_open_pr_number by head branch
# ---------------------------------------------------------------------------


@parametrize_adapters
def test_find_open_pr_number_by_head_branch(kind: str) -> None:
    if kind == GITHUB:
        routes = [("GET", "/pulls?head=o:bot/spec-17", Response([{"number": 42}]))]
    else:
        # Gitea /pulls has no head filter — adapter matches head.ref locally.
        routes = [
            (
                "GET",
                "/pulls",
                Response(
                    [
                        {"number": 41, "head": {"ref": "bot/spec-9"}},
                        {"number": 42, "head": {"ref": "bot/spec-17"}},
                    ]
                ),
            )
        ]
    client, _ = make_client(kind, "shadow", routes)

    assert client.find_open_pr_number("bot/spec-17") == 42


@parametrize_adapters
def test_find_open_pr_number_none_when_absent(kind: str) -> None:
    client, _ = make_client(kind, "shadow", [("GET", "/pulls", Response([]))])

    assert client.find_open_pr_number("bot/spec-404") is None


# ---------------------------------------------------------------------------
# has_merged_resolution_pr: exact-title semantics
# ---------------------------------------------------------------------------


def _resolution_routes(
    kind: str, titles: list[str], *, merged: bool = True
) -> list[tuple[str, str, Response]]:
    if kind == GITHUB:
        payload = {"total_count": len(titles), "items": [{"title": t} for t in titles]}
        return [("GET", "/search/issues", Response(payload))]
    return [
        ("GET", "/pulls", Response([{"title": t, "merged": merged} for t in titles]))
    ]


@parametrize_adapters
def test_has_merged_resolution_pr_exact_title_resolves(kind: str) -> None:
    routes = _resolution_routes(kind, ["impl: Issue #540 - Goose implementation"])
    client, _ = make_client(kind, "shadow", routes)

    assert client.has_merged_resolution_pr(540) is True


@parametrize_adapters
def test_has_merged_resolution_pr_loose_token_title_does_not_resolve(kind: str) -> None:
    """A PR that merely MENTIONS the issue must not resolve it — resolving on
    loose token matches silently drops issues from the pipeline (#1656)."""
    routes = _resolution_routes(kind, ["fix: regression caused by Issue #540 rollout"])
    client, _ = make_client(kind, "shadow", routes)

    assert client.has_merged_resolution_pr(540) is False


@parametrize_adapters
def test_has_merged_resolution_pr_rejects_number_prefix(kind: str) -> None:
    routes = _resolution_routes(kind, ["impl: Issue #5401 - other work"])
    client, _ = make_client(kind, "shadow", routes)

    assert client.has_merged_resolution_pr(540) is False


def test_gitea_closed_but_unmerged_pr_does_not_resolve() -> None:
    """Gitea lists closed pulls (no Search API); a closed-without-merge PR
    with a resolution title must not count as a resolution."""
    routes = _resolution_routes(
        GITEA, ["impl: Issue #540 - Goose implementation"], merged=False
    )
    client, _ = make_client(GITEA, "shadow", routes)

    assert client.has_merged_resolution_pr(540) is False


# ---------------------------------------------------------------------------
# label round-trip (Gitea id-lookup path exercised)
# ---------------------------------------------------------------------------


@parametrize_adapters
def test_add_remove_label_round_trip(kind: str) -> None:
    if kind == GITHUB:
        routes = [
            ("POST", "/issues/17/labels", Response([{"name": "needs-triage"}])),
            ("DELETE", "/issues/17/labels/needs-triage", Response(None)),
        ]
    else:
        routes = [
            (
                "GET",
                "/repos/o/r/labels",
                Response([{"id": 3, "name": "bug"}, {"id": 9, "name": "needs-triage"}]),
            ),
            (
                "POST",
                "/issues/17/labels",
                Response([{"id": 9, "name": "needs-triage"}]),
            ),
            ("DELETE", "/issues/17/labels/9", Response(None)),
        ]
    client, session = make_client(kind, "live", routes)

    client.add_label(17, "needs-triage")
    client.remove_label(17, "needs-triage")

    if kind == GITHUB:
        assert [c["method"] for c in session.calls] == ["POST", "DELETE"]
        assert session.calls[0]["kwargs"]["json"] == {"labels": ["needs-triage"]}
        assert session.calls[1]["url"].endswith("/issues/17/labels/needs-triage")
    else:
        # Gitea addresses labels by numeric id: one name -> id listing, then
        # cached per instance — the second mutation must NOT re-list.
        assert [c["method"] for c in session.calls] == ["GET", "POST", "DELETE"]
        assert session.calls[1]["kwargs"]["json"] == {"labels": [9]}
        assert session.calls[2]["url"].endswith("/issues/17/labels/9")


def test_gitea_unknown_label_fails_loudly() -> None:
    routes = [("GET", "/repos/o/r/labels", Response([{"id": 3, "name": "bug"}]))]
    client, session = make_client(GITEA, "live", routes)

    with pytest.raises(RuntimeError, match="label not found"):
        client.add_label(17, "needs-triage")

    assert [c["method"] for c in session.calls] == ["GET"]


# ---------------------------------------------------------------------------
# mode gates: shadow dry-runs, spec-only refuses, needs-human safety valve
# ---------------------------------------------------------------------------


@parametrize_adapters
def test_merge_pr_shadow_dry_runs_with_no_http_write(kind: str) -> None:
    client, session = make_client(kind, "shadow", [])

    result = client.merge_pr(7)

    assert isinstance(result, DryRunResult)
    assert result.dry_run is True
    assert result.operation == "merge_pr"
    assert session.calls == []
    assert client.dry_run_records == [result]


@parametrize_adapters
def test_merge_pr_spec_only_refused(kind: str) -> None:
    client, session = make_client(kind, "spec-only", [])

    with pytest.raises(PermissionError, match="merge_pr.*spec-only"):
        client.merge_pr(7)

    assert session.calls == []


@parametrize_adapters
def test_add_label_shadow_dry_runs_with_label_name(kind: str) -> None:
    client, session = make_client(kind, "shadow", [])

    result = client.add_label(17, "needs-triage")

    assert isinstance(result, DryRunResult)
    assert result.payload["labels"] == ["needs-triage"]
    assert session.calls == []


@parametrize_adapters
def test_spec_only_label_gate_blocks_non_spec_allows_needs_human(kind: str) -> None:
    """The spec-only gate must key on the label NAME on every host — on Gitea
    the needs-human check runs before name->id translation, otherwise the
    safety valve would silently stop matching."""
    if kind == GITHUB:
        routes = [("POST", "/issues/17/labels", Response([{"name": "needs-human"}]))]
    else:
        routes = [
            ("GET", "/repos/o/r/labels", Response([{"id": 5, "name": "needs-human"}])),
            ("POST", "/issues/17/labels", Response([{"id": 5, "name": "needs-human"}])),
        ]
    client, session = make_client(kind, "spec-only", routes)

    with pytest.raises(PermissionError, match="add_label.*spec-only"):
        client.add_label(17, "copilot-triaging")
    assert session.calls == []

    client.add_label(17, "needs-human")
    posts = [c for c in session.calls if c["method"] == "POST"]
    assert len(posts) == 1


# ---------------------------------------------------------------------------
# U1: create_issue — sanitise-gated, shadow dry-run, spec-only refused,
# live round-trip (Gitea label-id path), needs-human safety valve
# ---------------------------------------------------------------------------


@parametrize_adapters
def test_create_issue_shadow_dry_runs_with_no_http_write(kind: str) -> None:
    client, session = make_client(kind, "shadow", [])

    result = client.create_issue(title="t", body="b", labels=("needs-human",))

    assert isinstance(result, DryRunResult)
    assert result.operation == "create_issue"
    assert result.payload["title"] == "t"
    assert result.payload["labels"] == ["needs-human"]
    assert session.calls == []


@parametrize_adapters
def test_create_issue_spec_only_refused_without_needs_human(kind: str) -> None:
    client, session = make_client(kind, "spec-only", [])

    with pytest.raises(PermissionError, match="create_issue.*spec-only"):
        client.create_issue(title="t", body="b", labels=("bug",))

    assert session.calls == []


@parametrize_adapters
def test_create_issue_needs_human_safety_valve_allowed_in_spec_only(kind: str) -> None:
    if kind == GITHUB:
        routes = [("POST", "/repos/o/r/issues", Response({"number": 99}))]
    else:
        routes = [
            ("GET", "/repos/o/r/labels", Response([{"id": 5, "name": "needs-human"}])),
            ("POST", "/repos/o/r/issues", Response({"number": 99})),
        ]
    client, session = make_client(kind, "spec-only", routes)

    client.create_issue(title="esc", body="b", labels=("needs-human",))

    posts = [c for c in session.calls if c["method"] == "POST"]
    assert len(posts) == 1
    if kind == GITHUB:
        assert posts[0]["kwargs"]["json"]["labels"] == ["needs-human"]
    else:
        # Gitea: name translated to numeric id before the POST.
        assert posts[0]["kwargs"]["json"]["labels"] == [5]


@parametrize_adapters
def test_create_issue_live_round_trip(kind: str) -> None:
    if kind == GITHUB:
        routes = [("POST", "/repos/o/r/issues", Response({"number": 12}))]
    else:
        routes = [
            ("GET", "/repos/o/r/labels", Response([{"id": 7, "name": "bug"}])),
            ("POST", "/repos/o/r/issues", Response({"number": 12})),
        ]
    client, session = make_client(kind, "live", routes)

    client.create_issue(title="t", body="b", labels=("bug",))

    posts = [
        c for c in session.calls if c["method"] == "POST" and "/issues" in c["url"]
    ]
    assert len(posts) == 1


def test_create_issue_sanitise_fail_blocks_write() -> None:
    cfg = Config(target_repo="o/r", mode="shadow", wgmesh_bot_pat="author-pat")
    session = RoutingSession([])
    client = GitHubClient(cfg, session=session, sanitiser=lambda _t: False)

    with pytest.raises(Exception):  # SanitiseError
        client.create_issue(title="leak", body="b")

    assert session.calls == []


# ---------------------------------------------------------------------------
# U1: close_issue — comment (gated) + state PATCH; state_reason GitHub-only
# ---------------------------------------------------------------------------


@parametrize_adapters
def test_close_issue_shadow_dry_runs_no_http(kind: str) -> None:
    client, session = make_client(kind, "shadow", [])

    result = client.close_issue(7, "resolved by self-healing")

    assert isinstance(result, DryRunResult)
    assert result.operation == "close_issue"
    assert result.payload["state"] == "closed"
    # Two dry-run records: the gated comment, then the state PATCH.
    assert [r.operation for r in client.dry_run_records] == ["comment", "close_issue"]
    assert session.calls == []


@parametrize_adapters
def test_close_issue_spec_only_refused(kind: str) -> None:
    client, session = make_client(kind, "spec-only", [])

    with pytest.raises(PermissionError):
        client.close_issue(7, "reason")

    assert session.calls == []


@parametrize_adapters
def test_close_issue_live_comments_then_patches_state(kind: str) -> None:
    routes = [
        ("POST", "/issues/7/comments", Response({"id": 1})),
        ("PATCH", "/issues/7", Response({"number": 7, "state": "closed"})),
    ]
    client, session = make_client(kind, "live", routes)

    client.close_issue(7, "done", state_reason="not planned")

    methods = [c["method"] for c in session.calls]
    assert methods == ["POST", "PATCH"]
    patch_body = session.calls[1]["kwargs"]["json"]
    assert patch_body["state"] == "closed"
    if kind == GITHUB:
        # state_reason is a GitHub-only field; the adapter sends it.
        assert patch_body["state_reason"] == "not_planned"
    else:
        # Gitea PATCH issue has no state_reason — the seam drops it.
        assert "state_reason" not in patch_body


# ---------------------------------------------------------------------------
# U1: close_pr — comment (gated) + state PATCH on /pulls/{n}
# ---------------------------------------------------------------------------


@parametrize_adapters
def test_close_pr_shadow_dry_runs_no_http(kind: str) -> None:
    client, session = make_client(kind, "shadow", [])

    result = client.close_pr(8, "superseded")

    assert isinstance(result, DryRunResult)
    assert result.operation == "close_pr"
    assert [r.operation for r in client.dry_run_records] == ["comment", "close_pr"]
    assert session.calls == []


@parametrize_adapters
def test_close_pr_spec_only_refused(kind: str) -> None:
    client, session = make_client(kind, "spec-only", [])

    with pytest.raises(PermissionError):
        client.close_pr(8, "x")

    assert session.calls == []


@parametrize_adapters
def test_close_pr_live_comments_then_patches_pull_state(kind: str) -> None:
    routes = [
        ("POST", "/issues/8/comments", Response({"id": 1})),
        ("PATCH", "/pulls/8", Response({"number": 8, "state": "closed"})),
    ]
    client, session = make_client(kind, "live", routes)

    client.close_pr(8, "superseded")

    methods = [c["method"] for c in session.calls]
    assert methods == ["POST", "PATCH"]
    assert session.calls[1]["kwargs"]["json"]["state"] == "closed"


# ---------------------------------------------------------------------------
# U1: dispatch_workflow — GitHub Actions write; Gitea host-seam no-op
# ---------------------------------------------------------------------------


def test_dispatch_workflow_github_shadow_dry_runs() -> None:
    client, session = make_client(GITHUB, "shadow", [])

    result = client.dispatch_workflow("observation-loop.yml", {"signal": "idle"})

    assert isinstance(result, DryRunResult)
    assert result.operation == "dispatch_workflow"
    assert result.payload["inputs"] == {"signal": "idle"}
    assert session.calls == []


def test_dispatch_workflow_github_spec_only_refused() -> None:
    client, session = make_client(GITHUB, "spec-only", [])

    with pytest.raises(PermissionError, match="dispatch_workflow.*spec-only"):
        client.dispatch_workflow("observation-loop.yml", {})

    assert session.calls == []


def test_dispatch_workflow_github_live_posts_dispatch() -> None:
    routes = [
        ("POST", "/actions/workflows/observation-loop.yml/dispatches", Response(None)),
    ]
    client, session = make_client(GITHUB, "live", routes)

    client.dispatch_workflow("observation-loop.yml", {"signal": "idle"})

    assert len(session.calls) == 1
    body = session.calls[0]["kwargs"]["json"]
    assert body["inputs"] == {"signal": "idle"}
    assert body["ref"] == "main"


def test_dispatch_workflow_gitea_is_host_seam_noop() -> None:
    # The host seam: Forgejo has no workflow_dispatch the box depends on, so
    # this no-ops (records a marker, never an HTTP write) on EVERY mode.
    for mode in ("shadow", "live", "spec-only"):
        client, session = make_client(GITEA, mode, [])
        result = client.dispatch_workflow("observation-loop.yml", {"x": "1"})
        assert isinstance(result, DryRunResult)
        assert result.payload["unsupported_host"] == "gitea"
        assert session.calls == []


# ---------------------------------------------------------------------------
# QUACKBACK: composition adapter — issue methods → _qb (fake http_caller),
# PR methods → _gh (RoutingSession). Asserts the backend split and the
# client-side decision-status allowlist (KTD9). The GitHub/Gitea parametrized
# contract above is untouched — Quackback is a distinct two-transport object.
# ---------------------------------------------------------------------------


class _QBHttp:
    """Fake Quackback http_caller (transport-level): records and replies."""

    def __init__(self, routes: list[tuple[str, str, Any]]):
        self.routes = list(routes)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, headers: Any, body: bytes | None) -> Any:
        self.calls.append({"method": method, "url": url, "body": body})
        for route_method, fragment, response in self.routes:
            if route_method == method and fragment in url:
                return response
        raise AssertionError(f"unexpected qb request: {method} {url}")


def _make_quackback(
    qb_routes: list[tuple[str, str, Any]], gh_routes: list[tuple[str, str, Response]]
) -> tuple[Any, "_QBHttp", RoutingSession]:
    from wgmesh_pipeline.forge.quackback import QuackbackForge
    from wgmesh_pipeline.forge.quackback_client import QuackbackClient

    cfg = Config(
        target_repo="o/r",
        mode="live",
        wgmesh_bot_pat="author-pat",
        quackback_url="https://qb.example.com",
        quackback_token="qb_token",
    )
    qb_http = _QBHttp(qb_routes)
    gh_session = RoutingSession(gh_routes)
    gh = GitHubClient(cfg, session=gh_session, sanitiser=lambda _t: True)
    qb = QuackbackClient(cfg, http_caller=qb_http)
    forge = QuackbackForge(cfg, gh=gh, qb=qb, board_id="board_1")
    return forge, qb_http, gh_session


def test_quackback_issue_method_hits_qb_caller() -> None:
    from wgmesh_pipeline.forge.quackback_client import HttpResponse

    import json as _json

    forge, qb_http, gh_session = _make_quackback(
        qb_routes=[
            # U5: create_issue reads the board (dedup) and tags (resolution)
            # before the single POST that creates the tagged Build Suggestion.
            ("GET", "/api/v1/posts", HttpResponse(200, _json.dumps({"data": []}))),
            ("GET", "/api/v1/tags", HttpResponse(200, _json.dumps({"data": []}))),
            (
                "POST",
                "/api/v1/tags",
                HttpResponse(201, _json.dumps({"data": {"id": "t"}})),
            ),
            (
                "POST",
                "/api/v1/posts",
                HttpResponse(201, _json.dumps({"data": {"id": "post_1"}})),
            ),
        ],
        gh_routes=[],
    )

    post = forge.create_issue(title="t", body="b")

    assert post["id"] == "post_1"
    # Issue method hit the Quackback caller only — every request landed on the
    # Quackback HTTP layer, and the GitHub session was never touched.
    assert {c["method"] for c in qb_http.calls} <= {"GET", "POST"}
    assert any(
        c["method"] == "POST" and c["url"].endswith("/api/v1/posts")
        for c in qb_http.calls
    )
    assert gh_session.calls == []


def test_quackback_pr_method_hits_gh_session() -> None:
    forge, qb_http, gh_session = _make_quackback(
        qb_routes=[],
        gh_routes=[("POST", "/repos/o/r/pulls", Response({"number": 99}))],
    )

    result = forge.create_pr(title="t", head="bot/impl-1", base="main", body="b")

    assert result["number"] == 99
    # PR method routed to the GitHub session, never the Quackback caller.
    assert [c["method"] for c in gh_session.calls] == ["POST"]
    assert qb_http.calls == []


def test_quackback_set_status_accepted_for_build_raises_locally() -> None:
    from wgmesh_pipeline.forge.quackback_client import HttpResponse

    import json as _json

    forge, qb_http, gh_session = _make_quackback(
        qb_routes=[
            ("GET", "/api/v1/posts", HttpResponse(200, _json.dumps({"data": []}))),
            ("GET", "/api/v1/tags", HttpResponse(200, _json.dumps({"data": []}))),
            (
                "POST",
                "/api/v1/tags",
                HttpResponse(201, _json.dumps({"data": {"id": "t"}})),
            ),
            (
                "POST",
                "/api/v1/posts",
                HttpResponse(201, _json.dumps({"data": {"id": "post_1"}})),
            ),
        ],
        gh_routes=[],
    )
    forge.create_issue(title="t", body="b")
    before = len(qb_http.calls)

    with pytest.raises(PermissionError, match="Accepted for Build"):
        forge.set_status(1, "Accepted for Build")

    # The forbidden decision status is blocked locally — no extra HTTP write.
    assert len(qb_http.calls) == before
    assert gh_session.calls == []


# ---------------------------------------------------------------------------
# opt-in live Forgejo contract (docker-compose.gitea.yml)
# ---------------------------------------------------------------------------

gitea_live = pytest.mark.skipif(
    os.environ.get("GITEA_LIVE") != "1",
    reason=(
        "live Forgejo conformance is opt-in: start docker-compose.gitea.yml, "
        "then GITEA_LIVE=1 GITEA_TOKEN=... GITEA_REPO=owner/repo"
    ),
)


@gitea_live
class TestGiteaLiveContract:
    """Same contract against a real Forgejo at http://localhost:3000.

    Env: GITEA_LIVE=1, GITEA_TOKEN (author token), GITEA_REPO=owner/repo
    (default conformance/conformance).
    Bootstrap steps are documented in docker-compose.gitea.yml.
    """

    @pytest.fixture()
    def client(self) -> GiteaForge:
        import requests

        cfg = Config(
            target_repo=os.environ.get("GITEA_REPO", "conformance/conformance"),
            mode="live",
            wgmesh_bot_pat=os.environ["GITEA_TOKEN"],
        )
        return GiteaForge(cfg, session=requests.Session(), sanitiser=lambda _t: True)

    def test_issue_label_round_trip(self, client: GiteaForge) -> None:
        base = f"/repos/{client.config.owner}/{client.config.repo}"
        title = f"conformance: {uuid.uuid4().hex[:8]}"
        issue = client._request("POST", f"{base}/issues", json={"title": title})
        number = int(issue["number"])
        try:
            try:
                client._request(
                    "POST",
                    f"{base}/labels",
                    json={"name": "needs-triage", "color": "#ff0000"},
                )
            except Exception:
                pass  # label already exists from a prior run

            client.add_label(number, "needs-triage")
            listed = {i.number: i for i in client.list_open_issues()}
            assert number in listed
            assert "needs-triage" in listed[number].labels
            assert listed[number].pull_request is None

            client.remove_label(number, "needs-triage")
            listed = {i.number: i for i in client.list_open_issues()}
            assert "needs-triage" not in listed[number].labels
        finally:
            client._request(
                "PATCH", f"{base}/issues/{number}", json={"state": "closed"}
            )

    def test_has_merged_resolution_pr_false_for_unknown_issue(
        self, client: GiteaForge
    ) -> None:
        assert client.has_merged_resolution_pr(999_999_999) is False

    def test_find_open_pr_number_none_for_unknown_branch(
        self, client: GiteaForge
    ) -> None:
        assert client.find_open_pr_number(f"bot/spec-{uuid.uuid4().hex}") is None
