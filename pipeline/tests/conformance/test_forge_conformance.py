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
        reviewer_pat="reviewer-pat",
    )
    session = RoutingSession(routes)
    cls = GitHubClient if kind == GITHUB else GiteaForge
    return cls(cfg, session=session, sanitiser=lambda _text: True), session


# ---------------------------------------------------------------------------
# list_open_issues: host PR objects must be filtered
# ---------------------------------------------------------------------------


def _issues_payload(kind: str) -> list[dict[str, Any]]:
    real: dict[str, Any] = {"number": 10, "title": "Real issue", "labels": [], "state": "open"}
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
    # Contract: server-side needs-triage label filter on both hosts.
    # NOTE (encoded actual behavior): GitHubClient.list_needs_triage does NOT
    # filter pull_request objects — the bug #11 guard lives only on
    # list_open_issues. GiteaForge filters in both (see gitea-only test below)
    # because Gitea's issue listing is PR-heavy by default.
    payload = [item for item in _issues_payload(kind) if not item.get("pull_request")]
    client, session = make_client(kind, "shadow", [("GET", "/issues", Response(payload))])

    issues = client.list_needs_triage()

    assert [issue.number for issue in issues] == [10]
    assert session.calls[0]["kwargs"]["params"]["labels"] == "needs-triage"


def test_gitea_list_needs_triage_filters_pr_objects() -> None:
    client, _ = make_client(
        GITEA, "shadow", [("GET", "/issues", Response(_issues_payload(GITEA)))]
    )

    assert [issue.number for issue in client.list_needs_triage()] == [10]


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
            ("POST", "/issues/17/labels", Response([{"id": 9, "name": "needs-triage"}])),
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
# approve_pr: distinct reviewer principal
# ---------------------------------------------------------------------------


@parametrize_adapters
def test_approve_pr_uses_reviewer_credential_not_author_token(kind: str) -> None:
    routes = [("POST", "/pulls/7/reviews", Response({"id": 1, "state": "APPROVED"}))]
    client, session = make_client(kind, "live", routes)

    client.approve_pr(7)

    call = session.calls[0]
    auth = call["kwargs"]["headers"]["Authorization"]
    assert auth == "Bearer reviewer-pat"
    assert auth != "Bearer author-pat"
    # Host spelling divergence: GitHub's CreateReview event is "APPROVE",
    # Gitea's CreatePullReview expects "APPROVED".
    expected_event = "APPROVE" if kind == GITHUB else "APPROVED"
    assert call["kwargs"]["json"] == {"event": expected_event}


@parametrize_adapters
def test_approve_pr_shadow_dry_runs(kind: str) -> None:
    client, session = make_client(kind, "shadow", [])

    result = client.approve_pr(7)

    assert isinstance(result, DryRunResult)
    assert result.operation == "approve_pr"
    assert session.calls == []


@parametrize_adapters
def test_can_review_false_without_reviewer_credential(kind: str) -> None:
    cfg = Config(target_repo="o/r", mode="shadow", wgmesh_bot_pat="author-pat")
    cls = GitHubClient if kind == GITHUB else GiteaForge
    client = cls(cfg, session=RoutingSession([]), sanitiser=lambda _t: True)

    assert client.can_review() is False


# ---------------------------------------------------------------------------
# pr_checks_green: fail closed
# ---------------------------------------------------------------------------


def _checks_routes(kind: str, checks_response: Response) -> list[tuple[str, str, Response]]:
    pr_route = ("GET", "/pulls/7", Response({"head": {"sha": "abc123"}}))
    if kind == GITHUB:
        return [pr_route, ("GET", "/commits/abc123/check-runs", checks_response)]
    return [pr_route, ("GET", "/commits/abc123/status", checks_response)]


@parametrize_adapters
def test_pr_checks_green_fail_closed_when_no_checks(kind: str) -> None:
    empty = (
        Response({"check_runs": []})
        if kind == GITHUB
        else Response({"state": "", "statuses": []})
    )
    client, _ = make_client(kind, "shadow", _checks_routes(kind, empty))

    assert client.pr_checks_green(7) is False


@parametrize_adapters
def test_pr_checks_green_true_when_all_checks_succeed(kind: str) -> None:
    green = (
        Response({"check_runs": [{"status": "completed", "conclusion": "success"}]})
        if kind == GITHUB
        else Response({"state": "success", "statuses": [{"status": "success"}]})
    )
    client, _ = make_client(kind, "shadow", _checks_routes(kind, green))

    assert client.pr_checks_green(7) is True


@parametrize_adapters
def test_pr_checks_green_false_while_pending(kind: str) -> None:
    pending = (
        Response({"check_runs": [{"status": "in_progress", "conclusion": None}]})
        if kind == GITHUB
        else Response({"state": "pending", "statuses": [{"status": "pending"}]})
    )
    client, _ = make_client(kind, "shadow", _checks_routes(kind, pending))

    assert client.pr_checks_green(7) is False


def test_gitea_checks_success_state_without_statuses_is_not_green() -> None:
    """A combined state of success with ZERO statuses means nothing ran —
    fail closed, mirroring the GitHub adapter's empty check-runs case."""
    routes = _checks_routes(GITEA, Response({"state": "success", "statuses": []}))
    client, _ = make_client(GITEA, "shadow", routes)

    assert client.pr_checks_green(7) is False


# ---------------------------------------------------------------------------
# list_pr_approvals: latest review wins
# ---------------------------------------------------------------------------


@parametrize_adapters
def test_list_pr_approvals_latest_review_wins(kind: str) -> None:
    rejection = "CHANGES_REQUESTED" if kind == GITHUB else "REQUEST_CHANGES"
    reviews = [
        {"user": {"login": "rev-a"}, "state": "APPROVED"},
        {"user": {"login": "rev-a"}, "state": rejection},
        {"user": {"login": "rev-b"}, "state": "APPROVED"},
    ]
    client, _ = make_client(kind, "shadow", [("GET", "/pulls/7/reviews", Response(reviews))])

    assert client.list_pr_approvals(7) == ["rev-b"]


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
    (default conformance/conformance), optional GITEA_REVIEWER_TOKEN.
    Bootstrap steps are documented in docker-compose.gitea.yml.
    """

    @pytest.fixture()
    def client(self) -> GiteaForge:
        import requests

        cfg = Config(
            target_repo=os.environ.get("GITEA_REPO", "conformance/conformance"),
            mode="live",
            wgmesh_bot_pat=os.environ["GITEA_TOKEN"],
            reviewer_pat=os.environ.get("GITEA_REVIEWER_TOKEN"),
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
                    "POST", f"{base}/labels", json={"name": "needs-triage", "color": "#ff0000"}
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
            client._request("PATCH", f"{base}/issues/{number}", json={"state": "closed"})

    def test_has_merged_resolution_pr_false_for_unknown_issue(
        self, client: GiteaForge
    ) -> None:
        assert client.has_merged_resolution_pr(999_999_999) is False

    def test_find_open_pr_number_none_for_unknown_branch(
        self, client: GiteaForge
    ) -> None:
        assert client.find_open_pr_number(f"bot/spec-{uuid.uuid4().hex}") is None


@parametrize_adapters
def test_approve_pr_spec_only_refused(kind: str) -> None:
    client, _session = make_client(kind, "spec-only", [])

    with pytest.raises(PermissionError, match="approve_pr.*spec-only"):
        client.approve_pr(7)
