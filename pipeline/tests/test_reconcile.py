from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue
from wgmesh_pipeline.github.reconcile import reconcile_issues
from wgmesh_pipeline.state.store import StateStore


class Client(GitHubClient):
    def __init__(
        self,
        issues: Iterable[GitHubIssue],
        *,
        merged_resolution_prs: Iterable[int] = (),
        open_pr_branches: Iterable[str] = (),
        resolution_lookup_error: Exception | None = None,
    ):
        super().__init__(Config(target_repo="atvirokodosprendimai/wgmesh"))
        self._issues = list(issues)
        self._merged_resolution_prs = set(merged_resolution_prs)
        self._open_pr_branches = set(open_pr_branches)
        self._resolution_lookup_error = resolution_lookup_error
        self.removed_labels: list[tuple[int, str]] = []
        self.removed_label_flags: list[tuple[int, str, bool]] = []
        self.merged_resolution_lookups: list[int] = []
        self.open_pr_lookups: list[str] = []

    def list_open_issues(self) -> list[GitHubIssue]:
        return self._issues

    def has_merged_resolution_pr(self, issue_number: int) -> bool:
        self.merged_resolution_lookups.append(issue_number)
        if self._resolution_lookup_error is not None:
            raise self._resolution_lookup_error
        return issue_number in self._merged_resolution_prs

    def find_open_pr_number(self, head_branch: str) -> int | None:
        self.open_pr_lookups.append(head_branch)
        if head_branch in self._open_pr_branches:
            return 9000
        return None

    def remove_label(self, issue_number: int, label: str, *, spec_pr: bool = False):
        self.removed_labels.append((issue_number, label))
        self.removed_label_flags.append((issue_number, label, spec_pr))
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


def test_reopened_resolved_issue_without_rework_is_marked_merged_not_queued(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    client = Client([issue(510, (), title="Already fixed")], merged_resolution_prs={510})

    result = reconcile_issues(client, store)

    record = store.get_issue(510)
    assert result.merged == 1
    assert record.stage == "merged"
    assert record.status == "open"
    assert store.claim_next(now=datetime.now(timezone.utc)) is None
    assert client.open_pr_lookups == []


def test_reopened_resolved_issue_with_rework_and_no_open_bot_pr_is_requeued_and_label_cleared(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    client = Client([issue(540, ("needs-rework",), title="Redo")], merged_resolution_prs={540})

    result = reconcile_issues(client, store)

    claimed = store.claim_next(now=datetime.now(timezone.utc))
    assert result.merged == 0
    assert result.queued == 1
    assert claimed is not None
    assert claimed.number == 540
    assert claimed.stage == "queued"
    assert client.open_pr_lookups == ["bot/impl-540"]
    assert client.removed_label_flags == [(540, "needs-rework", True)]


def test_reopened_resolved_issue_with_rework_and_open_bot_pr_is_left_in_flight(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    client = Client(
        [issue(540, ("needs-rework",), title="Redo")],
        merged_resolution_prs={540},
        open_pr_branches={"bot/impl-540"},
    )

    result = reconcile_issues(client, store)

    assert result.merged == 0
    assert result.queued == 0
    assert store.claim_next(now=datetime.now(timezone.utc)) is None
    assert client.open_pr_lookups == ["bot/impl-540"]
    assert client.removed_labels == []


def test_reopened_issue_without_merged_resolution_pr_is_queued_as_before(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    client = Client([issue(700, (), title="New work")])

    reconcile_issues(client, store)

    claimed = store.claim_next(now=datetime.now(timezone.utc))
    assert claimed is not None
    assert claimed.number == 700
    assert claimed.stage == "queued"
    assert client.merged_resolution_lookups == [700]


def test_mid_flight_issue_with_merged_spec_pr_keeps_stage_and_skips_lookup(tmp_path) -> None:
    """An issue the box is actively working on (non-None stage in store) must
    NOT be marked merged when its spec PR merges mid-flight — the resolution
    lookup is for issues unknown to the store (fresh or post-reset_queue).
    Without this gate the box abandons every impl after its spec merges."""
    store = StateStore(tmp_path / "state.db")
    store.upsert_issue(609, "In flight", stage="spec_ready", status="open")
    client = Client([issue(609, (), title="In flight")], merged_resolution_prs={609})

    result = reconcile_issues(client, store)

    assert client.merged_resolution_lookups == []
    assert store.get_issue(609).stage == "spec_ready"
    assert result.merged == 0


def test_resolution_lookup_error_skips_issue_without_aborting_tick(tmp_path) -> None:
    """A failed lookup (e.g. search rate-limit 403) must neither abort the whole
    reconcile (stalls every claim) nor fail open (re-queues a resolved issue —
    the bug the guard exists to stop). The issue is skipped for this tick."""
    store = StateStore(tmp_path / "state.db")
    client = Client(
        [issue(510, (), title="Lookup fails"), issue(700, ("needs-triage",), title="Fine")],
        resolution_lookup_error=RuntimeError("403 rate limited"),
    )

    result = reconcile_issues(client, store)

    assert result.seen == 2
    assert result.queued == 1
    try:
        store.get_issue(510)
        raise AssertionError("issue 510 must not be upserted on lookup failure")
    except KeyError:
        pass
    assert store.get_issue(700).stage == "queued"


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


def test_injected_resolution_lookup_is_used_instead_of_client(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    client = Client([issue(510, (), title="Already fixed")])
    lookups: list[int] = []

    def lookup(number: int) -> bool:
        lookups.append(number)
        return True

    result = reconcile_issues(client, store, resolution_lookup=lookup)

    assert result.merged == 1
    assert lookups == [510]
    assert client.merged_resolution_lookups == []


def test_label_write_failure_does_not_block_reconcile(tmp_path) -> None:
    """Labels are mirrors, not gates: a failed needs-rework removal must not
    abort the tick or undo the requeue."""

    class LabelFailClient(Client):
        def remove_label(self, issue_number: int, label: str, *, spec_pr: bool = False):
            raise RuntimeError("label API down")

    store = StateStore(tmp_path / "state.db")
    client = LabelFailClient(
        [issue(540, ("needs-rework",), title="Redo")], merged_resolution_prs={540}
    )

    result = reconcile_issues(client, store)

    assert result.queued == 1
    assert store.get_issue(540).stage == "queued"
