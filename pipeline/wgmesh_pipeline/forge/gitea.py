"""Gitea/Forgejo forge adapter.

Satisfies ``wgmesh_pipeline.forge.protocol.Forge`` against the Gitea REST API
(``/api/v1``, GitHub-shaped). Extends ``GitHubClient`` deliberately: the write
gate (``_write``), the sanitise hooks, ``push_branch``'s git semantics and the
HTTP error shaping are host-neutral SAFETY machinery and must stay identical
across adapters (test-fakes-override-the-gate lesson) — only host-shaped
endpoints are overridden here. Divergences are absorbed in this adapter, never
in callers:

- labels are addressed by NAME in the protocol but by numeric id on Gitea
  (id lookup against ``/repos/{o}/{r}/labels``);
- no Search API: merged-resolution detection lists closed pulls and applies
  the same exact-title regex as the GitHub adapter;
- ``/pulls`` has no head-branch filter: open PRs are matched client-side on
  ``head.ref``;
- checks come from the commit-status API (``/commits/{sha}/status``), not
  GitHub check-runs;
- the issues endpoint includes ``"pull_request": null`` on plain issues
  (GitHub omits the key entirely), so PR filtering is on truthiness.

Endpoints that are byte-identical on both hosts (``get_pr``, ``comment``,
``create_pr``, ``update_pr_body``, ``push_branch``) are inherited unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.gitfacts import resolution_pattern as _resolution_pattern
from wgmesh_pipeline.forge.protocol import ForgeIssue
from wgmesh_pipeline.github.client import (
    DryRunResult,
    GitHubClient,
    Sanitiser,
    _parse_issue,
)

log = logging.getLogger("wgmesh_pipeline.forge.gitea")

DEFAULT_GITEA_URL = "http://localhost:3000"
PULLS_PAGE_SIZE = 50
LABELS_PAGE_SIZE = 100


class GiteaForge(GitHubClient):
    def __init__(
        self,
        config: Config,
        *,
        session: requests.Session | None = None,
        dry_run_records: list[DryRunResult] | None = None,
        sanitiser: Sanitiser | None = None,
    ):
        # GITEA_URL is wired through Config (load_config). Local default only
        # eases conformance runs; a real deployment must set it explicitly.
        base = (getattr(config, "gitea_url", None) or DEFAULT_GITEA_URL).rstrip("/")
        super().__init__(
            config,
            session=session,
            api_root=f"{base}/api/v1",
            dry_run_records=dry_run_records,
            sanitiser=sanitiser,
        )
        self._label_id_cache: dict[str, int] = {}

    # ------------------------------------------------------------------ reads

    def list_needs_triage(self) -> list[ForgeIssue]:
        data = self._request(
            "GET",
            f"{self._repo_base}/issues",
            params={"state": "open", "labels": "needs-triage", "type": "issues"},
        )
        return [
            _parse_issue(item) for item in data or [] if not item.get("pull_request")
        ]

    def list_open_issues(self) -> list[ForgeIssue]:
        data = self._request(
            "GET",
            f"{self._repo_base}/issues",
            params={"state": "open", "type": "issues"},
        )
        # Gitea models PRs as issues too. type=issues excludes them server-side
        # and the pull_request guard stays as belt-and-braces (bug #11: a box
        # that reconciles its own spec PRs as issues recurses into
        # spec-of-spec PRs). Unlike GitHub, Gitea includes
        # "pull_request": null on plain issues — filter on truthiness, not
        # key presence.
        return [
            _parse_issue(item) for item in data or [] if not item.get("pull_request")
        ]

    def get_issue(self, number: int) -> ForgeIssue | None:
        try:
            item = self._request("GET", f"{self._repo_base}/issues/{number}")
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 404:
                return None
            raise
        if item.get("pull_request"):
            return None
        return _parse_issue(item)

    def find_open_pr_number(self, head_branch: str) -> int | None:
        # Gitea's /pulls has no `head` filter param — list open pulls and
        # match client-side on head.ref.
        data = self._request(
            "GET",
            f"{self._repo_base}/pulls",
            params={"state": "open", "limit": PULLS_PAGE_SIZE},
        )
        for item in data or []:
            head_ref = (item.get("head") or {}).get("ref")
            if head_ref == head_branch and item.get("number") is not None:
                return int(item["number"])
        return None

    def has_merged_resolution_pr(self, issue_number: int) -> bool:
        """True if a MERGED resolution PR (impl/spec/fix) exists for the issue.

        Gitea has no cross-repo Search API; closed pulls are listed and titles
        verified locally against the exact resolution formats. Closed-but-
        unmerged PRs do not resolve. Bounded to the most recent
        PULLS_PAGE_SIZE closed pulls — acceptable because resolution PRs merge
        shortly after their issue is worked.
        """
        data = self._request(
            "GET",
            f"{self._repo_base}/pulls",
            params={"state": "closed", "limit": PULLS_PAGE_SIZE},
        )
        pattern = _resolution_pattern(issue_number)
        return any(
            item.get("merged") and pattern.match(str(item.get("title", "")))
            for item in data or []
        )

    def get_diff(self, pr_number: int) -> str:
        return self._request(
            "GET", f"{self._repo_base}/pulls/{pr_number}.diff", raw_text=True
        )

    # ----------------------------------------------------------------- writes

    def add_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any:
        return self._label_write("add_label", issue_number, label, spec_pr=spec_pr)

    def remove_label(
        self, issue_number: int, label: str, *, spec_pr: bool = False
    ) -> Any:
        return self._label_write("remove_label", issue_number, label, spec_pr=spec_pr)

    def create_issue(
        self, *, title: str, body: str, labels: tuple[str, ...] = ()
    ) -> Any:
        """Open an issue. Gitea addresses labels by numeric id (like
        ``add_label``), so names are translated to ids before the POST. The
        sanitise gate runs on the NAME-bearing payload exactly as the GitHub
        adapter does — shadow records names and never lists ids."""
        issues_path = f"{self._repo_base}/issues"
        if self.config.mode == "shadow":
            return self._write(
                "create_issue",
                "POST",
                issues_path,
                payload={"title": title, "body": body, "labels": list(labels)},
            )
        # Gate on the NAME-bearing payload (so the needs-human safety valve and
        # sanitise both see real labels) before translating to ids.
        self._sanitise_write("create_issue", {"title": title, "body": body})
        admits_needs_human = "needs-human" in labels
        if self.config.mode == "spec-only" and not admits_needs_human:
            raise PermissionError(
                "create_issue is not allowed when PIPELINE_MODE=spec-only"
            )
        label_ids = [self._label_id(name) for name in labels]
        return self._request(
            "POST",
            issues_path,
            json={"title": title, "body": body, "labels": label_ids},
        )

    def close_issue(
        self, number: int, reason: str, *, state_reason: str = "not_planned"
    ) -> Any:
        """Close with a rationale comment then flip state. Gitea's PATCH issue
        has NO ``state_reason`` field (GitHub-only), so it is dropped on the
        wire — the seam is absorbed here, callers stay host-neutral."""
        self.comment(number, reason)
        return self._write(
            "close_issue",
            "PATCH",
            f"{self._repo_base}/issues/{number}",
            payload={"state": "closed"},
        )

    def close_pr(self, number: int, comment: str) -> Any:
        """Comment then close. Gitea comments on PRs via the shared
        ``/issues/{n}/comments`` endpoint and closes via PATCH ``/pulls/{n}`` —
        both byte-identical to GitHub, so only the repo-base prefix differs."""
        self.comment(number, comment)
        return self._write(
            "close_pr",
            "PATCH",
            f"{self._repo_base}/pulls/{number}",
            payload={"state": "closed"},
        )

    def dispatch_workflow(self, workflow: str, inputs: dict[str, Any]) -> Any:
        """HOST SEAM: GitHub-Actions ``workflow_dispatch`` has no portable
        Forgejo equivalent the box relies on. Under the cutover the box's own
        loop replaces most retriggers, so this is a no-op-and-warn rather than a
        hard dependency. Returns a ``DryRunResult`` marker (no HTTP) on every
        mode so callers see the skip without a write."""
        log.warning(
            "dispatch_workflow(%r) unsupported on Gitea/Forgejo host — no-op "
            "(host seam; the box loop is the successor for retriggers)",
            workflow,
        )
        result = DryRunResult(
            dry_run=True,
            operation="dispatch_workflow",
            payload={
                "unsupported_host": "gitea",
                "workflow": workflow,
                "inputs": dict(inputs),
            },
        )
        self.dry_run_records.append(result)
        return result

    def merge_pr(self, pr_number: int, *, commit_title: str | None = None) -> Any:
        payload: dict[str, Any] = {"Do": "squash"}
        if commit_title:
            payload["MergeTitleField"] = commit_title
        return self._write(
            "merge_pr",
            "POST",
            f"{self._repo_base}/pulls/{pr_number}/merge",
            payload=payload,
        )

    # --------------------------------------------------------------- plumbing

    @property
    def _repo_base(self) -> str:
        return f"/repos/{self.config.owner}/{self.config.repo}"

    def _label_write(
        self, operation: str, issue_number: int, label: str, *, spec_pr: bool
    ) -> Any:
        labels_path = f"{self._repo_base}/issues/{issue_number}/labels"
        if self.config.mode == "shadow":
            # Dry-run through the shared write gate, recording the NAME —
            # shadow never touches the network, so no id lookup happens.
            return self._write(
                operation,
                "POST",
                labels_path,
                payload={"labels": [label]},
                spec_pr=spec_pr,
            )
        # Gate on the label NAME before translating to a Gitea id. This
        # mirrors GitHubClient._write exactly (spec-lane ops plus the
        # needs-human safety valve); the numeric id must never reach the gate
        # or the needs-human check would silently stop matching.
        allowed_spec_pr_write = spec_pr
        allowed_safety_write = operation == "add_label" and label == "needs-human"
        if self.config.mode == "spec-only" and not (
            allowed_spec_pr_write or allowed_safety_write
        ):
            raise PermissionError(
                f"{operation} is not allowed when PIPELINE_MODE=spec-only"
            )
        label_id = self._label_id(label)
        if operation == "add_label":
            return self._request("POST", labels_path, json={"labels": [label_id]})
        return self._request("DELETE", f"{labels_path}/{label_id}")

    def _label_id(self, name: str) -> int:
        # Per-instance cache: labels are repo-stable; without it every label
        # write costs an extra full-listing round trip per reconcile tick.
        cached = self._label_id_cache.get(name)
        if cached is not None:
            return cached
        data = self._request(
            "GET", f"{self._repo_base}/labels", params={"limit": LABELS_PAGE_SIZE}
        )
        for item in data or []:
            item_name = item.get("name")
            if item_name and item.get("id") is not None:
                self._label_id_cache[str(item_name)] = int(item["id"])
        if name in self._label_id_cache:
            return self._label_id_cache[name]
        # Fail loudly: a silently-skipped label write is how lifecycle gates
        # rot (defensive-guard-must-announce lesson).
        raise RuntimeError(f"label not found on {self.config.target_repo}: {name!r}")
