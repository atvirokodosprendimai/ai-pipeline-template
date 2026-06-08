from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue
from wgmesh_pipeline.github.reconcile import reconcile_issues
from wgmesh_pipeline.state.store import StateStore


class Client(GitHubClient):
    def __init__(self, issues: Iterable[GitHubIssue]):
        super().__init__(Config(target_repo="atvirokodosprendimai/wgmesh"))
        self._issues = list(issues)
        self.removed_labels: list[tuple[int, str]] = []

    def list_open_issues(self) -> list[GitHubIssue]:
        return self._issues

    def remove_label(self, issue_number: int, label: str, *, spec_pr: bool = False):
        self.removed_labels.append((issue_number, label))
        return {"ok": True}


class GatedClient(GitHubClient):
    """Keeps the REAL _write gate (so mode permissions are exercised) and only
    stubs the HTTP layer. Catches reconcile writes that omit spec_pr in
    spec-only mode -- the bug the fully-overriding Client above hid."""

    def __init__(self, issues: Iterable[GitHubIssue], *, mode: str):
        super().__init__(Config(target_repo="atvirokodosprendimai/wgmesh", mode=mode))
        self._issues = list(issues)
        self.requests: list[tuple[str, str]] = []

    def list_open_issues(self) -> list[GitHubIssue]:
        return self._issues

    def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path))
        return {"ok": True}


def issue(number: int, labels: tuple[str, ...], *, title: str = "title", state: str = "open") -> GitHubIssue:
    return GitHubIssue(number=number, title=title, labels=labels, state=state)


def test_new_needs_triage_issue_inserted_as_queued(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")

    result = reconcile_issues(Client([issue(1, ("needs-triage",), title="Fix")]), store)

    assert result.queued == 1
    assert store.get_issue(1).stage == "queued"
    assert store.get_issue(1).title == "Fix"


def test_in_flight_needs_triage_issue_is_not_reset_to_queued(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(17, "in flight", stage="specced")
    client = Client([issue(17, ("needs-triage",), title="Updated")])

    reconcile_issues(client, store)

    assert store.get_issue(17).stage == "specced"
    assert client.removed_labels == [(17, "needs-triage")]


def test_merged_upstream_issue_advances_and_is_not_requeued(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(1476, "done", stage="specced")

    reconcile_issues(Client([issue(1476, ("needs-triage", "merged"), state="open")]), store)

    record = store.get_issue(1476)
    assert record.stage == "merged"
    assert record.status == "closed"
    assert store.claim_next(now=datetime.now(timezone.utc)) is None


def test_needs_human_label_escalates_and_excludes_from_claim(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")

    reconcile_issues(Client([issue(2, ("needs-human",))]), store)

    assert store.get_issue(2).stage == "escalated"
    assert store.claim_next(now=datetime.now(timezone.utc)) is None


def test_reconcile_removes_needs_triage_without_raising_in_spec_only(tmp_path) -> None:
    # Regression: in spec-only the write-gate blocks remove_label unless
    # spec_pr=True. reconcile omitting the flag raised PermissionError every
    # tick and stalled the whole loop. Exercise the REAL gate here.
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(42, "in flight", stage="triaged")
    client = GatedClient([issue(42, ("needs-triage",))], mode="spec-only")

    reconcile_issues(client, store)  # must not raise

    assert ("DELETE", "/repos/atvirokodosprendimai/wgmesh/issues/42/labels/needs-triage") in client.requests
    assert store.get_issue(42).stage == "triaged"


def test_reconcile_then_claim_returns_only_actionable_issue(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    reconcile_issues(
        Client(
            [
                issue(1, ("needs-human",)),
                issue(2, ("needs-triage",), title="Do it"),
            ]
        ),
        store,
    )

    claimed = store.claim_next(now=datetime.now(timezone.utc))

    assert claimed is not None
    assert claimed.number == 2
