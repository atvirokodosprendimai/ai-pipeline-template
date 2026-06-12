from __future__ import annotations

import subprocess
from dataclasses import replace
from typing import Any

import pytest
import requests

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import DryRunResult, GitHubClient


class Response:
    def __init__(self, data: Any = None, text: str | None = None):
        self._data = data
        self.text = text if text is not None else ("" if data is None else "json")

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._data


class Session:
    def __init__(self, response: Response):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self.response


class ErrorResponse(Response):
    def __init__(self, status_code: int, text: str):
        super().__init__(text=text)
        self.status_code = status_code

    def raise_for_status(self) -> None:
        raise requests.HTTPError(f"{self.status_code} Error", response=self)


@pytest.fixture
def cfg() -> Config:
    return Config(target_repo="atvirokodosprendimai/wgmesh", mode="shadow", wgmesh_bot_pat="pat")


def test_list_needs_triage_returns_parsed_issues(cfg: Config) -> None:
    session = Session(
        Response(
            [
                {
                    "number": 17,
                    "title": "Fix mesh",
                    "labels": [{"name": "needs-triage"}, {"name": "fn:dev"}],
                    "state": "open",
                }
            ]
        )
    )

    issues = GitHubClient(cfg, session=session).list_needs_triage()

    assert issues[0].number == 17
    assert issues[0].labels == ("needs-triage", "fn:dev")
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["kwargs"]["params"]["labels"] == "needs-triage"


def test_request_http_error_includes_response_body(cfg: Config) -> None:
    body = '{"message":"Validation Failed","errors":[{"message":"Head does not exist"}]}'
    session = Session(ErrorResponse(422, body))
    client = GitHubClient(cfg, session=session)

    with pytest.raises(requests.HTTPError) as exc_info:
        client.list_needs_triage()

    assert body in str(exc_info.value)
    assert exc_info.value.response is session.response


def test_shadow_create_pr_dry_runs_with_no_network_write(cfg: Config) -> None:
    session = Session(Response({"number": 1}))
    client = GitHubClient(cfg, session=session)

    result = client.create_pr(title="spec: Issue #17 - Fix", head="bot/spec-17", base="main", body="body")

    assert isinstance(result, DryRunResult)
    assert result.dry_run is True
    assert result.operation == "create_pr"
    assert result.payload["title"] == "spec: Issue #17 - Fix"
    assert session.calls == []
    assert client.dry_run_records == [result]


def test_create_pr_refuses_unsanitisable_body_even_in_shadow(cfg: Config) -> None:
    session = Session(Response({"number": 1}))
    client = GitHubClient(cfg, session=session, sanitiser=lambda text: "SECRET" not in text)

    with pytest.raises(RuntimeError, match="create_pr body"):
        client.create_pr(title="spec: Issue #17 - Fix", head="bot/spec-17", base="main", body="SECRET_KEY=abc123")

    assert session.calls == []
    assert client.dry_run_records == []


def test_push_branch_refuses_unsanitisable_spec_even_in_shadow(tmp_path, cfg: Config) -> None:
    spec = tmp_path / "specs" / "issue-17-spec.md"
    spec.parent.mkdir()
    spec.write_text("SECRET_KEY=abc123")
    client = GitHubClient(cfg, sanitiser=lambda text: "SECRET" not in text)

    with pytest.raises(RuntimeError, match="specs/issue-17-spec.md"):
        client.push_branch(str(tmp_path), "bot/spec-17")

    assert client.dry_run_records == []


def test_spec_branch_refuses_nonmatching_spec_path(tmp_path, cfg: Config) -> None:
    spec = tmp_path / "specs" / "foo.md"
    spec.parent.mkdir()
    spec.write_text("## Spec\nsafe\n")
    client = GitHubClient(replace(cfg, mode="spec-only"), sanitiser=lambda text: True)

    with pytest.raises(RuntimeError, match="expected spec file missing: specs/issue-17-spec.md"):
        client.push_branch(str(tmp_path), "bot/spec-17", spec_pr=True)

    assert client.dry_run_records == []


def test_spec_branch_sanitises_changed_files_outside_issue_spec_glob(tmp_path, cfg: Config) -> None:
    spec = tmp_path / "specs" / "issue-17-spec.md"
    spec.parent.mkdir()
    spec.write_text("## Spec\nsafe\n")
    extra = tmp_path / "docs" / "x.md"
    extra.parent.mkdir()
    extra.write_text("SECRET_KEY=abc123")
    client = GitHubClient(cfg, sanitiser=lambda text: "SECRET" not in text)

    with pytest.raises(RuntimeError, match="docs/x.md"):
        client.push_branch(str(tmp_path), "bot/spec-17", spec_pr=True)

    assert client.dry_run_records == []


def test_merge_pr_shadow_dry_runs_live_calls_endpoint_once(cfg: Config) -> None:
    shadow_session = Session(Response({"merged": True}))
    shadow = GitHubClient(cfg, session=shadow_session)
    assert shadow.merge_pr(7).dry_run is True
    assert shadow_session.calls == []

    live_session = Session(Response({"merged": True}))
    live = GitHubClient(replace(cfg, mode="live"), session=live_session)
    assert live.merge_pr(7) == {"merged": True}
    assert len(live_session.calls) == 1
    assert live_session.calls[0]["method"] == "PUT"
    assert live_session.calls[0]["url"].endswith("/pulls/7/merge")


def test_spec_only_refuses_non_spec_write(cfg: Config) -> None:
    session = Session(Response({"ok": True}))
    client = GitHubClient(replace(cfg, mode="spec-only"), session=session)

    with pytest.raises(PermissionError, match="spec-only"):
        client.comment(17, "not allowed")

    assert session.calls == []


def test_spec_only_refuses_merge_write(cfg: Config) -> None:
    session = Session(Response({"merged": True}))
    client = GitHubClient(replace(cfg, mode="spec-only"), session=session)

    with pytest.raises(PermissionError, match="merge_pr.*spec-only"):
        client.merge_pr(17)

    assert session.calls == []


def test_spec_only_allows_spec_pr_create_with_mocked_network(cfg: Config) -> None:
    session = Session(Response({"number": 99}))
    client = GitHubClient(replace(cfg, mode="spec-only"), session=session)

    result = client.create_pr(
        title="spec: Issue #17 - Fix mesh",
        head="bot/spec-17",
        base="main",
        body="spec body",
        spec_pr=True,
    )

    assert result == {"number": 99}
    assert len(session.calls) == 1
    assert session.calls[0]["method"] == "POST"


def test_spec_only_create_pr_requires_explicit_spec_pr_authority(cfg: Config) -> None:
    session = Session(Response({"number": 99}))
    client = GitHubClient(replace(cfg, mode="spec-only"), session=session)

    with pytest.raises(PermissionError, match="create_pr.*spec-only"):
        client.create_pr(
            title="spec: Issue #17 - Fix mesh",
            head="bot/spec-17",
            base="main",
            body="spec body",
        )

    assert session.calls == []


def test_spec_only_allows_spec_branch_push_and_label_swap(cfg: Config, tmp_path, monkeypatch) -> None:
    spec = tmp_path / "specs" / "issue-17-spec.md"
    spec.parent.mkdir()
    spec.write_text("## Classification\nfix\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it\n")
    session = Session(Response({"ok": True}))
    client = GitHubClient(replace(cfg, mode="spec-only"), session=session, sanitiser=lambda text: True)
    pushes: list[tuple[list[str], str]] = []

    def fake_run(command, *, cwd, check, text, capture_output, timeout):
        pushes.append((command, cwd))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("wgmesh_pipeline.github.client.subprocess.run", fake_run)

    client.push_branch(str(tmp_path), "bot/spec-17", spec_pr=True)
    client.remove_label(17, "needs-triage", spec_pr=True)
    client.add_label(17, "copilot-triaging", spec_pr=True)

    # bot/spec-* push is force (bug #12: re-spec after reset diverges from the
    # prior run's remote branch -> plain push rejected non-fast-forward).
    assert pushes == [(["git", "push", "--force", "origin", "bot/spec-17"], str(tmp_path))]
    assert [call["method"] for call in session.calls] == ["DELETE", "POST"]


def test_live_impl_branch_push_is_force_updated(cfg: Config, tmp_path, monkeypatch) -> None:
    client = GitHubClient(replace(cfg, mode="live"), sanitiser=lambda text: True)
    pushes: list[tuple[list[str], str]] = []

    def fake_run(command, *, cwd, check, text, capture_output, timeout):
        pushes.append((command, cwd))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("wgmesh_pipeline.github.client.subprocess.run", fake_run)

    client.push_branch(str(tmp_path), "bot/impl-17")

    assert pushes == [(["git", "push", "--force", "origin", "bot/impl-17"], str(tmp_path))]


def test_list_open_issues_filters_out_pull_requests(cfg: Config) -> None:
    """GitHub's issues endpoint returns PRs too (they carry a pull_request
    key). They must be filtered, else the box reconciles its own spec PRs as
    issues and recurses into spec-of-spec PRs (bug #11)."""
    session = Session(
        Response(
            [
                {"number": 10, "title": "Real issue", "labels": [], "state": "open"},
                {
                    "number": 667,
                    "title": "spec: Issue #652 - ...",
                    "labels": [],
                    "state": "open",
                    "pull_request": {"url": "https://api.github.com/.../pulls/667"},
                },
            ]
        )
    )

    issues = GitHubClient(cfg, session=session).list_open_issues()

    assert [i.number for i in issues] == [10]


def _search_response(*titles: str) -> Response:
    return Response({"total_count": len(titles), "items": [{"title": t} for t in titles]})


def test_has_merged_resolution_pr_matches_exact_prefix_title(cfg: Config) -> None:
    session = Session(_search_response("impl: Issue #540 - Goose implementation"))

    client = GitHubClient(cfg, session=session)

    assert client.has_merged_resolution_pr(540) is True
    assert len(session.calls) == 1
    assert "/search/issues" in session.calls[0]["url"]


def test_has_merged_resolution_pr_accepts_copilot_era_spec_suffix(cfg: Config) -> None:
    session = Session(
        _search_response("spec: Add `wgmesh status --json` output format (Issue #510)")
    )

    assert GitHubClient(cfg, session=session).has_merged_resolution_pr(510) is True


def test_has_merged_resolution_pr_rejects_loose_token_match(cfg: Config) -> None:
    """Search-API quoted phrases are token-loose: a query for "impl: Issue #540"
    also returns PRs that merely mention the issue. A referencing PR must not
    mark the issue resolved — that silently drops it from the pipeline."""
    session = Session(_search_response("fix: regression caused by Issue #540 rollout"))

    assert GitHubClient(cfg, session=session).has_merged_resolution_pr(540) is False


def test_has_merged_resolution_pr_rejects_number_prefix_match(cfg: Config) -> None:
    session = Session(_search_response("impl: Issue #5401 - other work"))

    assert GitHubClient(cfg, session=session).has_merged_resolution_pr(540) is False


def test_has_merged_resolution_pr_rejects_alphanumeric_continuation(cfg: Config) -> None:
    session = Session(_search_response("impl: Issue #540A - other work"))

    assert GitHubClient(cfg, session=session).has_merged_resolution_pr(540) is False


def test_list_needs_triage_filters_out_pull_requests(cfg: Config) -> None:
    """Same bug-#11 guard as list_open_issues: a needs-triage-labeled PR must
    not re-enter triage as an issue. Truthiness check — Gitea-shaped payloads
    carry "pull_request": null for plain issues."""
    session = Session(
        Response(
            [
                {"number": 10, "title": "Real issue", "labels": [], "state": "open"},
                {"number": 11, "title": "Null pr key", "labels": [], "state": "open", "pull_request": None},
                {
                    "number": 667,
                    "title": "spec: Issue #652 - ...",
                    "labels": [],
                    "state": "open",
                    "pull_request": {"url": "https://api.github.com/.../pulls/667"},
                },
            ]
        )
    )

    issues = GitHubClient(cfg, session=session).list_needs_triage()

    assert [i.number for i in issues] == [10, 11]
