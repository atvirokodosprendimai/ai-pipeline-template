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
``create_pr``, ``update_pr_body``, ``approve_pr``, ``push_branch``) are
inherited unchanged.
"""

from __future__ import annotations

from typing import Any

import requests

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.protocol import ForgeIssue
from wgmesh_pipeline.github.client import (
    DryRunResult,
    GitHubClient,
    Sanitiser,
    _parse_issue,
)

DEFAULT_GITEA_URL = "http://localhost:3000"
PULLS_PAGE_SIZE = 50
LABELS_PAGE_SIZE = 100


# Resolution-title matching is shared with gitfacts — one pattern, one
# divergence surface (the squash "(#N)" suffix group is harmless for PR
# titles).
from wgmesh_pipeline.forge.gitfacts import resolution_pattern as _resolution_pattern


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
        return [_parse_issue(item) for item in data or [] if not item.get("pull_request")]

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
        return [_parse_issue(item) for item in data or [] if not item.get("pull_request")]

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

    def pr_checks_green(self, pr_number: int) -> bool:
        """Combined commit status on the PR head is success. No statuses at
        all counts as NOT green — fail closed, exactly like the GitHub
        adapter's no-check-runs case."""
        pr = self.get_pr(pr_number)
        sha = (pr.get("head") or {}).get("sha")
        if not sha:
            return False
        data = self._request("GET", f"{self._repo_base}/commits/{sha}/status")
        statuses = (data or {}).get("statuses") or []
        if not statuses:
            return False
        return (data or {}).get("state") == "success"

    def list_pr_approvals(self, pr_number: int) -> list[str]:
        """Logins whose LATEST review on the PR is an approval."""
        reviews = self._request(
            "GET",
            f"{self._repo_base}/pulls/{pr_number}/reviews",
            params={"limit": LABELS_PAGE_SIZE},
        )
        latest: dict[str, str] = {}
        for review in reviews or []:
            login = str(((review.get("user") or {}).get("login")) or "")
            state = str(review.get("state") or "")
            # Gitea spells rejection REQUEST_CHANGES (GitHub: CHANGES_REQUESTED);
            # accept both so latest-wins works regardless of host spelling.
            if login and state in {
                "APPROVED",
                "REQUEST_CHANGES",
                "CHANGES_REQUESTED",
                "DISMISSED",
            }:
                latest[login] = state
        return [login for login, state in latest.items() if state == "APPROVED"]

    # ----------------------------------------------------------------- writes

    def add_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any:
        return self._label_write("add_label", issue_number, label, spec_pr=spec_pr)

    def remove_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any:
        return self._label_write("remove_label", issue_number, label, spec_pr=spec_pr)

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
                operation, "POST", labels_path, payload={"labels": [label]}, spec_pr=spec_pr
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

    def approve_pr(self, pr_number: int) -> Any:
        """Gitea's CreatePullReview expects event \"APPROVED\" (GitHub uses
        \"APPROVE\"). Same reviewer-credential semantics as the base class."""
        if not self.config.reviewer_pat:
            raise RuntimeError("approve_pr requires WGMESH_REVIEWER_PAT (reviewer identity)")
        if self.config.mode == "shadow":
            result = DryRunResult(
                dry_run=True, operation="approve_pr", payload={"pr": pr_number, "event": "APPROVED"}
            )
            self.dry_run_records.append(result)
            return result
        if self.config.mode == "spec-only":
            raise PermissionError("approve_pr is not allowed when PIPELINE_MODE=spec-only")
        return self._request(
            "POST",
            f"{self._repo_base}/pulls/{pr_number}/reviews",
            json={"event": "APPROVED"},
            headers={"Authorization": f"Bearer {self.config.reviewer_pat}"},
        )
