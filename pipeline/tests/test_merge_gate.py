from __future__ import annotations

from typing import Any

from wgmesh_pipeline.forge.merge_gate import ensure_mergeable


class ReviewClient:
    def __init__(
        self,
        *,
        checks_green: bool = True,
        author: str = "author-bot",
        approvals: list[str] | None = None,
        reviewer_credential: bool = False,
    ):
        self._checks_green = checks_green
        self._author = author
        self._approvals = list(approvals or [])
        self._reviewer_credential = reviewer_credential
        self.approve_calls: list[int] = []

    def get_pr(self, number: int) -> dict[str, Any]:
        return {"user": {"login": self._author}}

    def pr_checks_green(self, pr_number: int) -> bool:
        return self._checks_green

    def list_pr_approvals(self, pr_number: int) -> list[str]:
        return self._approvals

    def can_review(self) -> bool:
        return self._reviewer_credential

    def approve_pr(self, pr_number: int) -> Any:
        self.approve_calls.append(pr_number)
        return {"state": "APPROVED"}


def test_red_ci_is_not_ready() -> None:
    client = ReviewClient(checks_green=False, approvals=["someone-else"])

    readiness = ensure_mergeable(client, 7)

    assert readiness.ready is False
    assert "ci not green" in readiness.reasons


def test_green_with_distinct_approval_is_ready() -> None:
    client = ReviewClient(approvals=["reviewer-bot"])

    readiness = ensure_mergeable(client, 7)

    assert readiness.ready is True
    assert client.approve_calls == []


def test_author_self_approval_does_not_count() -> None:
    """The live 422 lesson: an approval from the PR author's own identity is
    not a distinct principal."""
    client = ReviewClient(approvals=["author-bot"], reviewer_credential=False)

    readiness = ensure_mergeable(client, 7)

    assert readiness.ready is False
    assert any("distinct" in r for r in readiness.reasons)


def test_missing_approval_with_reviewer_credential_self_serves() -> None:
    client = ReviewClient(approvals=[], reviewer_credential=True)

    readiness = ensure_mergeable(client, 7)

    assert readiness.ready is True
    assert client.approve_calls == [7]


def test_missing_approval_without_reviewer_credential_escalates() -> None:
    client = ReviewClient(approvals=[], reviewer_credential=False)

    readiness = ensure_mergeable(client, 7)

    assert readiness.ready is False
    assert client.approve_calls == []


def test_red_ci_with_reviewer_credential_defers_approval() -> None:
    """Don't burn a reviewer approval on a red build — it goes stale by the
    time CI is fixed and re-pushed."""
    client = ReviewClient(checks_green=False, approvals=[], reviewer_credential=True)

    readiness = ensure_mergeable(client, 7)

    assert readiness.ready is False
    assert client.approve_calls == []
    assert any("deferred while ci not green" in r for r in readiness.reasons)


def test_approve_failure_becomes_readiness_reason_not_exception() -> None:
    """A 422 (same-identity misconfig) or expired reviewer PAT must surface
    as not-ready -> escalation, never as an exception that strands the issue
    mid-merge."""

    class FailingApprove(ReviewClient):
        def approve_pr(self, pr_number: int):
            raise RuntimeError("422 Can not approve your own pull request")

    client = FailingApprove(approvals=[], reviewer_credential=True)

    readiness = ensure_mergeable(client, 7)

    assert readiness.ready is False
    assert any("reviewer approval failed" in r for r in readiness.reasons)
