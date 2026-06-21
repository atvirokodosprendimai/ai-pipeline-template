"""Quackback forge adapter — composition, not subclass (KTD1).

``QuackbackForge`` satisfies the ``Forge`` protocol structurally by *holding*
two rooted backends and splitting every method between them explicitly:

  - issue/post methods  → ``self._qb`` (a ``QuackbackClient``): the decision
    board is the issue surface;
  - PR/branch/merge methods → ``self._gh`` (a ``GitHubClient``): code still
    lives on GitHub.

Subclassing ``GitHubClient`` (the Gitea precedent) retargets a *single*
``api_root`` and so can only speak one transport; this integration needs two
from one object, which only composition expresses.

Seams absorbed here, callers stay host-neutral:

  - **int↔string id seam (KTD6/OQ3).** The ``Forge`` protocol is int-keyed but
    Quackback post ids are opaque strings (``post_…``). A monotonic in-memory
    ``dict[int, str]`` is populated when ``create_issue`` returns and translated
    on ``get_issue`` / ``comment`` / ``set_status``.
    # U4: replace with store-backed quackback_post_id mapping.
  - **decision-status authority (KTD9).** ``set_status`` enforces the
    client-side allowlist locally — the SOLE guard, since Quackback keys are
    all-or-nothing and cannot be scoped server-side.
  - **sanitise wall.** ``create_issue`` runs the GitHubClient ``_sanitise_write``
    gate on the name-bearing payload before the post is created, exactly as the
    Gitea adapter does.
"""

from __future__ import annotations

import logging
import os
from itertools import count
from typing import Any

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.protocol import ForgeIssue
from wgmesh_pipeline.forge.quackback_client import QuackbackClient
from wgmesh_pipeline.forge.quackback_status import (
    ACCEPTED_FOR_BUILD,
    BOX_SETTABLE_STATUSES,
    is_box_settable,
)
from wgmesh_pipeline.github.client import GitHubClient

log = logging.getLogger("wgmesh_pipeline.forge.quackback")

# Tags the Observation Loop's Build Suggestions carry (R1).
BUILD_SUGGESTION_TAGS: tuple[str, ...] = ("agent-suggestion", "build-candidate")
# Env override for the Build Suggestions board id. Read from the environment
# (not Config) to keep the U1 Config surface untouched — this is a U2 concern.
BOARD_ID_ENV = "QUACKBACK_BOARD_ID"


class QuackbackForge:
    """Composition adapter: ``_qb`` for posts, ``_gh`` for PRs (KTD1)."""

    def __init__(
        self,
        config: Config,
        *,
        gh: GitHubClient | None = None,
        qb: QuackbackClient | None = None,
        board_id: str | None = None,
    ):
        self.config = config
        self._gh = gh if gh is not None else GitHubClient(config)
        self._qb = qb if qb is not None else QuackbackClient(config)
        self._board_id = board_id or os.environ.get(BOARD_ID_ENV)
        # int↔string id seam (KTD6). Monotonic ints handed to int-keyed callers.
        self._id_map: dict[int, str] = {}
        self._id_counter = count(1)
        # name→statusId cache (statuses are board-stable).
        self._status_id_cache: dict[str, str] = {}

    # ------------------------------------------------------- post → _qb (issues)

    def create_issue(
        self, *, title: str, body: str, labels: tuple[str, ...] = ()
    ) -> Any:
        """Create a Build Suggestion post on the board. The sanitise wall runs on
        the title+body before the post is created, mirroring the Gitea adapter's
        gate on the name-bearing payload."""
        if not self._board_id:
            raise RuntimeError(
                f"QuackbackForge.create_issue requires a board id (set {BOARD_ID_ENV})"
            )
        # Reuse the GitHubClient sanitise wall (public-repo safety, KTD10).
        self._gh._sanitise_write("create_issue", {"title": title, "body": body})
        post = self._qb.create_post(self._board_id, title, body)
        post_id = str(post.get("id") or "")
        if not post_id:
            raise RuntimeError("Quackback create_post returned a post without an id")
        number = next(self._id_counter)
        self._id_map[number] = post_id
        return post

    def get_issue(self, number: int) -> ForgeIssue | None:
        post_id = self._id_map.get(number)
        if post_id is None:
            return None
        post = self._qb.get_post(post_id)
        return _post_to_issue(number, post)

    def list_needs_triage(self) -> list[ForgeIssue]:
        """HOST SEAM: GitHub needs-triage labels have no Quackback analogue —
        ingest is by decision status (``list_open_issues`` → Accepted for Build,
        KTD3), so triage is empty by design and never queries the board."""
        return []

    def close_issue(
        self, number: int, reason: str, *, state_reason: str = "not_planned"
    ) -> Any:
        """HOST SEAM: closing a post is a human DECISION (Rejected / Cancelled),
        which the box must never author (KTD9). No-op-and-warn rather than
        forging a decision the founder owns."""
        log.warning(
            "close_issue(%r) is a no-op on Quackback — closing a post is a human "
            "decision status the box may not author (KTD9)",
            number,
        )
        return None

    def list_open_issues(self) -> list[ForgeIssue]:
        """The ingest read (KTD3): only ``Accepted for Build`` posts.

        Fail-closed — an API error propagates, never an empty-looks-healthy list
        (KTD5). Posts are mapped to stable ints, registering the id seam for
        later per-item reads.
        """
        slug = self._slug_for(ACCEPTED_FOR_BUILD)
        page = self._qb.list_posts(status_slug=slug)
        issues: list[ForgeIssue] = []
        for post in page.get("data", []):
            post_id = str(post.get("id") or "")
            if not post_id:
                continue
            number = self._number_for(post_id)
            issues.append(_post_to_issue(number, post))
        return issues

    def comment(self, issue_number: int, body: str) -> Any:
        post_id = self._require_post_id(issue_number)
        return self._qb.comment(post_id, body)

    def set_status(self, number: int, status: str) -> Any:
        """Flip a post's status — but only within the box-settable allowlist.

        Client-side allowlist (KTD9): the box may never author a decision status
        (``Accepted for Build`` / ``Rejected`` / etc.); those raise locally. This
        is the SOLE guard, since Quackback keys cannot be scoped server-side.
        """
        if not is_box_settable(status):
            raise PermissionError(
                f"QuackbackForge may not set status {status!r}; "
                f"box-settable statuses are {sorted(BOX_SETTABLE_STATUSES)}"
            )
        post_id = self._require_post_id(number)
        status_id = self._status_id_for(status)
        return self._qb.set_post_status(post_id, status_id)

    # ---------------------------------------------------------- PR → _gh

    def get_pr(self, number: int) -> dict[str, Any]:
        return self._gh.get_pr(number)

    def find_open_pr_number(self, head_branch: str) -> int | None:
        return self._gh.find_open_pr_number(head_branch)

    def has_merged_resolution_pr(self, issue_number: int) -> bool:
        return self._gh.has_merged_resolution_pr(issue_number)

    def get_diff(self, pr_number: int) -> str:
        return self._gh.get_diff(pr_number)

    def create_pr(
        self, *, title: str, head: str, base: str, body: str, spec_pr: bool = False
    ) -> Any:
        return self._gh.create_pr(
            title=title, head=head, base=base, body=body, spec_pr=spec_pr
        )

    def update_pr_body(self, pr_number: int, body: str) -> Any:
        return self._gh.update_pr_body(pr_number, body)

    def merge_pr(self, pr_number: int, *, commit_title: str | None = None) -> Any:
        return self._gh.merge_pr(pr_number, commit_title=commit_title)

    def enable_auto_merge(self, pr_number: int, *, merge_method: str = "SQUASH") -> Any:
        return self._gh.enable_auto_merge(pr_number, merge_method=merge_method)

    def push_branch(
        self, clone_path: str, branch: str, *, spec_pr: bool = False
    ) -> Any:
        return self._gh.push_branch(clone_path, branch, spec_pr=spec_pr)

    def close_pr(self, number: int, comment: str) -> Any:
        return self._gh.close_pr(number, comment)

    def dispatch_workflow(self, workflow: str, inputs: dict[str, Any]) -> Any:
        return self._gh.dispatch_workflow(workflow, inputs)

    # Labels are a GitHub PR concern here → _gh (the conformance split routes
    # them to the code backend, not the decision board).
    def add_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any:
        return self._gh.add_label(issue_number, label, spec_pr=spec_pr)

    def remove_label(
        self, issue_number: int, label: str, *, spec_pr: bool = False
    ) -> Any:
        return self._gh.remove_label(issue_number, label, spec_pr=spec_pr)

    # --------------------------------------------------------------- plumbing

    def _require_post_id(self, number: int) -> str:
        post_id = self._id_map.get(number)
        if post_id is None:
            raise KeyError(f"no Quackback post mapped to int handle {number}")
        return post_id

    def _number_for(self, post_id: str) -> int:
        for number, mapped in self._id_map.items():
            if mapped == post_id:
                return number
        number = next(self._id_counter)
        self._id_map[number] = post_id
        return number

    def _slug_for(self, status_name: str) -> str:
        for status in self._qb.list_statuses():
            if status.get("name") == status_name:
                slug = status.get("slug")
                if slug:
                    return str(slug)
        raise RuntimeError(f"Quackback status not found: {status_name!r}")

    def _status_id_for(self, status_name: str) -> str:
        cached = self._status_id_cache.get(status_name)
        if cached is not None:
            return cached
        for status in self._qb.list_statuses():
            name = status.get("name")
            status_id = status.get("id")
            if name and status_id is not None:
                self._status_id_cache[str(name)] = str(status_id)
        resolved = self._status_id_cache.get(status_name)
        if resolved is None:
            raise RuntimeError(f"Quackback status not found: {status_name!r}")
        return resolved


def _post_to_issue(number: int, post: dict[str, Any]) -> ForgeIssue:
    """Map a Quackback post to the host-neutral ``ForgeIssue`` (int-keyed)."""
    tags = post.get("tags") or []
    labels = tuple(tag["name"] if isinstance(tag, dict) else str(tag) for tag in tags)
    return ForgeIssue(
        number=number,
        title=str(post.get("title", "")),
        labels=labels,
        state="open" if post.get("deletedAt") in (None, "") else "closed",
    )
