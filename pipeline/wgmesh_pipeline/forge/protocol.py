"""Host-neutral forge surface.

The pipeline's SDLC must not depend on a specific git host. This protocol is
the contract every forge adapter (GitHub today, Gitea/Forgejo next) satisfies;
pipeline code depends on it, never on a concrete adapter. The method set is
exactly the surface the box uses — grown deliberately, not speculatively.

Vocabulary: "PR" in method names means the host's change-request object
(pull request on GitHub/Gitea, merge request on GitLab). The `spec_pr`
keyword on write methods is box policy (the spec-lane write gate), not host
policy — every adapter must thread it through to the shared write gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ForgeIssue:
    number: int
    title: str
    labels: tuple[str, ...]
    state: str
    pull_request: dict[str, Any] | None = None


@runtime_checkable
class Forge(Protocol):
    def list_needs_triage(self) -> list[ForgeIssue]: ...

    def list_open_issues(self) -> list[ForgeIssue]: ...

    def get_pr(self, number: int) -> dict[str, Any]: ...

    def find_open_pr_number(self, head_branch: str) -> int | None: ...

    def has_merged_resolution_pr(self, issue_number: int) -> bool: ...

    def get_diff(self, pr_number: int) -> str: ...

    def add_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any: ...

    def remove_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any: ...

    def comment(self, issue_number: int, body: str) -> Any: ...

    def create_issue(
        self, *, title: str, body: str, labels: tuple[str, ...] = ()
    ) -> Any: ...

    def close_issue(
        self, number: int, reason: str, *, state_reason: str = "not_planned"
    ) -> Any: ...

    def close_pr(self, number: int, comment: str) -> Any: ...

    def dispatch_workflow(self, workflow: str, inputs: dict[str, Any]) -> Any: ...

    def create_pr(
        self, *, title: str, head: str, base: str, body: str, spec_pr: bool = False
    ) -> Any: ...

    def update_pr_body(self, pr_number: int, body: str) -> Any: ...

    def merge_pr(self, pr_number: int, *, commit_title: str | None = None) -> Any: ...

    def push_branch(self, clone_path: str, branch: str, *, spec_pr: bool = False) -> Any: ...

    def pr_checks_green(self, pr_number: int) -> bool: ...

    def list_pr_approvals(self, pr_number: int) -> list[str]: ...

    def can_review(self) -> bool: ...

    def approve_pr(self, pr_number: int) -> Any: ...
