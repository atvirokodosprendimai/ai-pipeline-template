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
import re
from itertools import count
from typing import Any, Callable

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
        gh_client: GitHubClient | None = None,
        qb_client: QuackbackClient | None = None,
        board_id: str | None = None,
        post_id_resolver: Callable[[int], str | None] | None = None,
    ):
        self.config = config
        # Param names carry a _client suffix so the forge-agnostic gh-free-gate
        # (which forbids the GitHub CLI token in runtime code) never
        # false-matches a constructor argument.
        self._gh = gh_client if gh_client is not None else GitHubClient(config)
        self._qb = qb_client if qb_client is not None else QuackbackClient(config)
        # Prefer the explicit arg, then Config (promoted in the cutover U2), then
        # the env var (back-compat). load_config fail-closes when forge_kind is
        # quackback and the board id is unset, so this is non-None in production.
        self._board_id = (
            board_id
            or getattr(config, "quackback_board_id", None)
            or os.environ.get(BOARD_ID_ENV)
        )
        # Store-backed fallback resolver for ids not in the in-memory _id_map.
        # Posts ingested via the U4 store mapping (reconcile_quackback) never
        # touched _id_map, so set_status/comment/get_issue would KeyError on them
        # without this fallback (U6). Bound lazily via bind_resolver too.
        self._post_id_resolver = post_id_resolver
        # int↔string id seam (KTD6). Monotonic ints handed to int-keyed callers.
        self._id_map: dict[int, str] = {}
        self._id_counter = count(1)
        # name→statusId cache (statuses are board-stable).
        self._status_id_cache: dict[str, str] = {}
        # name→tagId cache (tags are board-stable; resolved create-if-missing).
        self._tag_id_cache: dict[str, str] = {}

    # ------------------------------------------------------- post → _qb (issues)

    def create_issue(
        self, *, title: str, body: str, labels: tuple[str, ...] = ()
    ) -> Any:
        """Emit an Observation-Loop Build Suggestion on the board (U5).

        Order is load-bearing:

          1. **sanitise wall** on the name-bearing payload FIRST — a leaking
             title/body must be blocked before any board read or write,
             mirroring the Gitea adapter's gate (KTD10);
          2. **cross-status dedup** — list every board post (no status filter)
             and, on a normalized-title match, comment the new body on the
             existing post and return it (no new post);
          3. otherwise resolve the Build-Suggestion + label tag ids and create
             a tagged post at the board default status (Open for Vote).
        """
        if not self._board_id:
            raise RuntimeError(
                f"QuackbackForge.create_issue requires a board id (set {BOARD_ID_ENV})"
            )
        # 1. Reuse the GitHubClient sanitise wall (public-repo safety, KTD10).
        self._gh._sanitise_write("create_issue", {"title": title, "body": body})

        # 2. Cross-status dedup against existing board posts.
        existing = self._find_duplicate_post(title)
        if existing is not None:
            existing_id = str(existing.get("id") or "")
            if existing_id:
                self._qb.comment(existing_id, body)
                self._number_for(existing_id)
                return existing

        # 3. Resolve tags and create the tagged Build Suggestion.
        tag_ids = self._resolve_tag_ids(BUILD_SUGGESTION_TAGS + tuple(labels))
        post = self._qb.create_post(self._board_id, title, body, tag_ids=tag_ids)
        post_id = str(post.get("id") or "")
        if not post_id:
            raise RuntimeError("Quackback create_post returned a post without an id")
        number = next(self._id_counter)
        self._id_map[number] = post_id
        return post

    def get_issue(self, number: int) -> ForgeIssue | None:
        post_id = self._lookup_post_id(number)
        if post_id is None:
            return None
        post = self._qb.get_post(post_id)
        return _post_to_issue(number, post)

    def get_decision_status(self, number: int) -> str | None:
        """The human-readable decision status of the post mapped to ``number``.

        Resolves the post id via the same in-memory→store fallback as the write
        path, fetches the post, and maps its ``statusId`` to a status NAME via
        the cached ``/statuses`` lookup. Returns the name (e.g. "Accepted for
        Build", "Cancelled") or ``None`` when the post id, the post, or the
        status mapping is unresolvable. Reads — never writes — so it carries no
        allowlist guard; the U12 drift guard in the poller decides what an
        out-of-lane (or unresolvable) read means."""
        post_id = self._lookup_post_id(number)
        if post_id is None:
            return None
        post = self._qb.get_post(post_id)
        status_id = post.get("statusId")
        if status_id in (None, ""):
            return None
        return self._status_name_for(str(status_id))

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

    def list_accepted_posts(self) -> list[dict[str, Any]]:
        """Raw ``Accepted for Build`` post dicts for the U4 ingest (KTD3).

        ``reconcile_quackback`` needs ``id`` + ``updatedAt`` (the accept marker),
        which the host-neutral ``ForgeIssue`` does not carry — so this returns the
        unmapped post dicts rather than ``ForgeIssue``. Fail-closed: an API error
        propagates, never an empty-looks-healthy list (KTD5)."""
        slug = self._slug_for(ACCEPTED_FOR_BUILD)
        page = self._qb.list_posts(status_slug=slug)
        return list(page.get("data", []))

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

    def get_pr_mergeable(self, number: int) -> str | None:
        return self._gh.get_pr_mergeable(number)

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

    def bind_resolver(self, resolver: Callable[[int], str | None]) -> None:
        """Bind the store-backed post-id resolver after construction (U6).

        The poller wires ``store.quackback_post_id_for`` here so the write/read
        path resolves ids for posts ingested via the store mapping (which never
        populated the in-memory ``_id_map``)."""
        self._post_id_resolver = resolver

    def post_url(self, number: int) -> str | None:
        """The Quackback post URL for ``number`` (``<QUACKBACK_URL>/posts/<id>``),
        or ``None`` when the post id or base URL is unresolvable (R4)."""
        post_id = self._lookup_post_id(number)
        base = getattr(self.config, "quackback_url", None)
        if post_id is None or not base:
            return None
        return f"{str(base).rstrip('/')}/posts/{post_id}"

    def _lookup_post_id(self, number: int) -> str | None:
        """Resolve a post id: in-memory ``_id_map`` first, then the store-backed
        resolver (if bound), else ``None``."""
        post_id = self._id_map.get(number)
        if post_id is not None:
            return post_id
        if self._post_id_resolver is not None:
            return self._post_id_resolver(number)
        return None

    def _require_post_id(self, number: int) -> str:
        post_id = self._lookup_post_id(number)
        if post_id is None:
            raise KeyError(f"no Quackback post mapped to int handle {number}")
        return post_id

    def _status_name_for(self, status_id: str) -> str | None:
        """Reverse of ``_status_id_for``: a statusId → its status NAME, or None.

        Caches the same name→id map as ``_status_id_for`` and inverts it; an
        unknown id (status removed/renamed) yields ``None`` rather than raising —
        a mirror-time read must not crash the tick loop."""
        if not self._status_id_cache:
            for status in self._qb.list_statuses():
                name = status.get("name")
                sid = status.get("id")
                if name and sid is not None:
                    self._status_id_cache[str(name)] = str(sid)
        for name, sid in self._status_id_cache.items():
            if sid == status_id:
                return name
        return None

    def _number_for(self, post_id: str) -> int:
        for number, mapped in self._id_map.items():
            if mapped == post_id:
                return number
        number = next(self._id_counter)
        self._id_map[number] = post_id
        return number

    # Bound on how many board posts the dedup read pages through, so a large
    # board cannot make every Build Suggestion an unbounded scan.
    _DEDUP_MAX_POSTS = 500

    def _find_duplicate_post(self, title: str) -> dict[str, Any] | None:
        """Return an existing board post whose title matches ``title`` after
        normalization (case/space/punctuation-insensitive), else None.

        Lists posts with NO status filter so a duplicate is caught regardless of
        where it already sits in the funnel (the cross-status guarantee). Paged
        up to ``_DEDUP_MAX_POSTS`` via the cursor; an API error propagates
        (fail-closed) rather than silently skipping dedup."""
        target = _normalize_title(title)
        if not target:
            return None
        seen = 0
        cursor: str | None = None
        while seen < self._DEDUP_MAX_POSTS:
            page = self._qb.list_posts(cursor=cursor, limit=100)
            posts = page.get("data", [])
            for post in posts:
                seen += 1
                if _normalize_title(str(post.get("title", ""))) == target:
                    return post
            pagination = (page.get("meta") or {}).get("pagination") or {}
            cursor = pagination.get("cursor")
            if not pagination.get("hasMore") or not cursor or not posts:
                break
        return None

    def _resolve_tag_ids(self, names: tuple[str, ...]) -> list[str]:
        """Map tag names → ids, creating any that don't yet exist.

        The board tag list is fetched once and cached; a name absent from the
        cache is created (``create_tag``) and its id reused thereafter."""
        if not self._tag_id_cache:
            for tag in self._qb.list_tags():
                name = tag.get("name")
                tag_id = tag.get("id")
                if name and tag_id is not None:
                    self._tag_id_cache[str(name)] = str(tag_id)
        ids: list[str] = []
        for name in names:
            tag_id = self._tag_id_cache.get(name)
            if tag_id is None:
                created = self._qb.create_tag(name)
                tag_id = str(created.get("id") or "")
                if not tag_id:
                    raise RuntimeError(
                        f"Quackback create_tag returned no id for tag {name!r}"
                    )
                self._tag_id_cache[name] = tag_id
            if tag_id not in ids:
                ids.append(tag_id)
        return ids

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


def _normalize_title(title: str) -> str:
    """Lowercase, collapse all non-alphanumeric runs to single spaces, strip.

    Deliberately simple normalized-equality (not fuzzy overlap): a title is a
    duplicate only when it reduces to the same alphanumeric token sequence —
    case, spacing, and punctuation are ignored, nothing more clever."""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


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
