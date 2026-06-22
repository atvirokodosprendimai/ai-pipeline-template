from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.protocol import ForgeIssue

API_ROOT = "https://api.github.com"
SANITISE_SCRIPT = (
    Path(__file__).resolve().parents[3] / "company" / "scripts" / "sanitise.sh"
)
GIT_TIMEOUT_SECONDS = 120
# Ref the workflow_dispatch fires against. The box's retrigger/observation-loop
# dispatches target the default branch; a constant (not a Config field) keeps
# this U1 surface minimal — revisit if a non-main dispatch ref is ever needed.
WORKFLOW_DISPATCH_REF = "main"
HTTP_TIMEOUT_SECONDS = 30
SANITISE_TIMEOUT_SECONDS = 120
OPEN_ISSUES_PAGE_SIZE = 100
OPEN_ISSUES_MAX_PAGES = 50
Sanitiser = Callable[[str], bool]

log = logging.getLogger("wgmesh_pipeline.github.client")


class SanitiseError(RuntimeError):
    pass


# Backwards-compatible alias: the host-neutral dataclass lives in
# forge/protocol.py; existing imports of GitHubIssue keep working.
GitHubIssue = ForgeIssue


@dataclass(frozen=True)
class DryRunResult:
    dry_run: bool
    operation: str
    payload: dict[str, Any]


class GitHubClient:
    def __init__(
        self,
        config: Config,
        *,
        session: requests.Session | None = None,
        api_root: str = API_ROOT,
        dry_run_records: list[DryRunResult] | None = None,
        sanitiser: Sanitiser | None = None,
    ):
        self.config = config
        self.session = session or requests.Session()
        self.api_root = api_root.rstrip("/")
        self.dry_run_records = dry_run_records if dry_run_records is not None else []
        self._sanitiser = sanitiser

    def list_needs_triage(self) -> list[GitHubIssue]:
        data = self._request(
            "GET",
            f"/repos/{self.config.owner}/{self.config.repo}/issues",
            params={"state": "open", "labels": "needs-triage"},
        )
        # Same PR filter as list_open_issues (bug #11): a labeled PR returned
        # by the issues endpoint must not re-enter triage as an issue.
        # Truthiness, not key presence — Gitea sends "pull_request": null.
        return [_parse_issue(item) for item in data if not item.get("pull_request")]

    def list_open_issues(self) -> list[GitHubIssue]:
        # GitHub's issues endpoint returns pull requests too (they carry a
        # "pull_request" key). Skip them — reconciling the box's own spec PRs
        # as issues caused a runaway: spec-of-spec PRs with exploding chained
        # titles (bug #11).
        issues: list[GitHubIssue] = []
        for page in range(1, OPEN_ISSUES_MAX_PAGES + 1):
            data = self._request(
                "GET",
                f"/repos/{self.config.owner}/{self.config.repo}/issues",
                params={
                    "state": "open",
                    "per_page": OPEN_ISSUES_PAGE_SIZE,
                    "page": page,
                },
            )
            issues.extend(
                _parse_issue(item) for item in data if "pull_request" not in item
            )
            if len(data) < OPEN_ISSUES_PAGE_SIZE:
                break
        else:
            log.warning(
                "list_open_issues pagination truncated after %s pages for %s/%s",
                OPEN_ISSUES_MAX_PAGES,
                self.config.owner,
                self.config.repo,
            )
        return issues

    def get_issue(self, number: int) -> GitHubIssue | None:
        try:
            item = self._request(
                "GET",
                f"/repos/{self.config.owner}/{self.config.repo}/issues/{number}",
            )
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 404:
                return None
            raise
        # Same PR filter as list_open_issues (bug #11): direct issue reads can
        # return host PR objects from the shared issues endpoint.
        if "pull_request" in item:
            return None
        return _parse_issue(item)

    def get_pr(self, number: int) -> dict[str, Any]:
        return self._request(
            "GET", f"/repos/{self.config.owner}/{self.config.repo}/pulls/{number}"
        )

    def get_pr_mergeable(self, number: int) -> str | None:
        """Tri-state mergeability for conflict-heal: ``"CONFLICTING"`` /
        ``"MERGEABLE"`` / ``None``. GitHub's REST ``mergeable`` is ``null``
        until the server finishes computing it after a push — return ``None``
        so the caller skips this cycle and recomputes next run (never infer
        not-conflicting from null)."""
        mergeable = self.get_pr(number).get("mergeable")
        if mergeable is None:
            return None
        return "CONFLICTING" if mergeable is False else "MERGEABLE"

    def compare_behind_by(self, head_branch: str, *, base: str = "main") -> int:
        """Commits ``head_branch`` is behind ``base`` (GitHub compare
        ``behind_by``). The stale-base-heal 'stale tree' signal: a branch cut
        before a since-merged fix is behind main. A deleted branch / 404 /
        missing field resolves to 0 — not a rebase candidate."""
        owner = self.config.owner
        try:
            resp = self._request(
                "GET",
                f"/repos/{owner}/{self.config.repo}/compare/{base}...{head_branch}",
            )
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 404:
                return 0
            raise
        behind = resp.get("behind_by") if isinstance(resp, dict) else None
        return int(behind) if isinstance(behind, int) else 0

    def pr_has_failing_check(self, number: int) -> bool:
        """True iff any check on the PR's head commit concluded FAILURE — the
        stale-base-heal 'broken' signal. Covers both the Checks API
        (Actions, e.g. build-test) and legacy commit statuses, matching the
        ``statusCheckRollup`` the retired Actions executor read via its CLI."""
        head_sha = (self.get_pr(number).get("head") or {}).get("sha")
        if not head_sha:
            return False
        owner = self.config.owner
        base = f"/repos/{owner}/{self.config.repo}/commits/{head_sha}"
        runs = self._request("GET", f"{base}/check-runs")
        check_runs = runs.get("check_runs") or [] if isinstance(runs, dict) else []
        if any(
            str(r.get("conclusion") or "").upper() == "FAILURE" for r in check_runs
        ):
            return True
        status = self._request("GET", f"{base}/status")
        statuses = status.get("statuses") or [] if isinstance(status, dict) else []
        return any(
            str(s.get("state") or "").lower() in ("failure", "error")
            for s in statuses
        )

    def list_open_pull_requests(
        self, *, per_page: int = 100, max_prs: int = 200
    ) -> list[dict[str, Any]]:
        """All open pull requests: ``[{number, headRefName}]``.

        Paginates up to ``max_prs`` PRs total (sane cap; the box's repos are
        small). Used by the merge-lane-heal module to build the gather set from
        which the three planners (conflict/rearm/stale-base) select their
        candidates. Returns plain dicts so callers can augment them without
        mutating the API object."""
        owner = self.config.owner
        results: list[dict[str, Any]] = []
        page = 1
        while len(results) < max_prs:
            batch = self._request(
                "GET",
                f"/repos/{owner}/{self.config.repo}/pulls",
                params={"state": "open", "per_page": per_page, "page": page},
            )
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                results.append({
                    "number": int(item["number"]),
                    "headRefName": str(item.get("head", {}).get("ref") or ""),
                })
                if len(results) >= max_prs:
                    break
            if len(batch) < per_page:
                break
            page += 1
        return results

    def find_open_pr_number(self, head_branch: str) -> int | None:
        """Open PR number for a head branch, or None. Used to make spec PR
        creation idempotent: a retry after a partial run hits create_pr 422
        ('a pull request already exists') and reuses the existing PR."""
        owner = self.config.owner
        resp = self._request(
            "GET",
            f"/repos/{owner}/{self.config.repo}/pulls?head={owner}:{head_branch}&state=open",
        )
        if isinstance(resp, list) and resp and resp[0].get("number") is not None:
            return int(resp[0]["number"])
        return None

    def has_merged_resolution_pr(self, issue_number: int) -> bool:
        """True if a merged resolution PR (impl/spec/fix) exists for the issue.

        Search-API quoted phrases are token-loose — a query for
        "spec: Issue #510" also matches 'spec: Add ... (Issue #510)' and PRs
        that merely mention the issue — so search is only a candidate
        generator; titles are verified locally against the exact resolution
        formats. One call total, not one per prefix: search counts against
        the 30-requests/minute search budget, not the core API budget.
        """
        owner = self.config.owner
        repo = self.config.repo
        data = self._request(
            "GET",
            "/search/issues",
            params={
                "q": f'repo:{owner}/{repo} is:pr is:merged in:title "Issue #{issue_number}"',
                "per_page": 30,
            },
        )
        from wgmesh_pipeline.forge.gitfacts import resolution_pattern

        items = data.get("items") or []
        pattern = resolution_pattern(issue_number)
        return any(pattern.match(str(item.get("title", ""))) for item in items)

    def get_diff(self, pr_number: int) -> str:
        return self._request(
            "GET",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls/{pr_number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
            raw_text=True,
        )

    def add_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any:
        return self._write(
            "add_label",
            "POST",
            f"/repos/{self.config.owner}/{self.config.repo}/issues/{issue_number}/labels",
            payload={"labels": [label]},
            spec_pr=spec_pr,
        )

    def remove_label(
        self, issue_number: int, label: str, *, spec_pr: bool = False
    ) -> Any:
        return self._write(
            "remove_label",
            "DELETE",
            f"/repos/{self.config.owner}/{self.config.repo}/issues/{issue_number}/labels/{label}",
            payload={},
            spec_pr=spec_pr,
        )

    def comment(self, issue_number: int, body: str) -> Any:
        return self._write(
            "comment",
            "POST",
            f"/repos/{self.config.owner}/{self.config.repo}/issues/{issue_number}/comments",
            payload={"body": body},
        )

    def set_status(self, number: int, status: str) -> Any:
        """HOST SEAM: decision-status is a Quackback concept. GitHub Issues have
        no equivalent free-form status the box drives, so this no-ops-and-warns
        (records a marker, never an HTTP write) — keeping GitHub/Gitea adapters
        structurally conformant with the Forge protocol's ``set_status`` without
        introducing a GitHub label-status convention the box doesn't use."""
        log.warning(
            "set_status(%r, %r) unsupported on GitHub-shaped host — no-op "
            "(host seam; decision status is a Quackback-only concept)",
            number,
            status,
        )
        result = DryRunResult(
            dry_run=True,
            operation="set_status",
            payload={"unsupported_host": "github", "number": number, "status": status},
        )
        self.dry_run_records.append(result)
        return result

    def create_issue(
        self, *, title: str, body: str, labels: tuple[str, ...] = ()
    ) -> Any:
        """Open a new issue. Title + body are LLM/heal-derived, so both pass
        the sanitise gate inside ``_write`` (LLM-emit lesson). ``labels`` may
        carry ``needs-human`` — the spec-only safety valve below admits that
        one creation just as it admits the ``add_label`` valve."""
        return self._write(
            "create_issue",
            "POST",
            f"/repos/{self.config.owner}/{self.config.repo}/issues",
            payload={"title": title, "body": body, "labels": list(labels)},
        )

    def close_issue(
        self, number: int, reason: str, *, state_reason: str = "not_planned"
    ) -> Any:
        """Close an issue with a human-facing rationale comment, then flip its
        state. The comment carries the LLM/heal reason and is sanitise-gated by
        ``comment``; the state PATCH carries no free text. ``state_reason`` is
        ``not planned`` by default — ``completed`` is reserved for the
        merged-impl-PR closer (observation R5)."""
        self.comment(number, reason)
        # Accept the gh-CLI phrasing ("not planned") callers use and send the
        # REST API form ("not_planned"); valid values: completed|not_planned|reopened.
        api_state_reason = state_reason.strip().lower().replace(" ", "_")
        return self._write(
            "close_issue",
            "PATCH",
            f"/repos/{self.config.owner}/{self.config.repo}/issues/{number}",
            payload={"state": "closed", "state_reason": api_state_reason},
        )

    def close_pr(self, number: int, comment: str) -> Any:
        """Comment, then close a pull request. The comment endpoint is shared
        with issues on GitHub (``/issues/{n}/comments``) and is sanitise-gated;
        the state PATCH on ``/pulls/{n}`` carries no free text."""
        self.comment(number, comment)
        return self._write(
            "close_pr",
            "PATCH",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls/{number}",
            payload={"state": "closed"},
        )

    def dispatch_workflow(self, workflow: str, inputs: dict[str, Any]) -> Any:
        """Trigger a GitHub Actions workflow_dispatch. Host-specific by design
        (see protocol/seam note); a non-Actions forge overrides this with a
        no-op-and-warn. The ref defaults to the configured base branch. Goes
        through ``_write`` so shadow records a dry-run and spec-only refuses."""
        return self._write(
            "dispatch_workflow",
            "POST",
            f"/repos/{self.config.owner}/{self.config.repo}/actions/workflows/{workflow}/dispatches",
            payload={"ref": WORKFLOW_DISPATCH_REF, "inputs": dict(inputs)},
        )

    def create_pr(
        self,
        *,
        title: str,
        head: str,
        base: str,
        body: str,
        spec_pr: bool = False,
    ) -> Any:
        return self._write(
            "create_pr",
            "POST",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls",
            payload={"title": title, "head": head, "base": base, "body": body},
            spec_pr=spec_pr,
        )

    def update_pr_body(self, pr_number: int, body: str) -> Any:
        return self._write(
            "update_pr",
            "PATCH",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls/{pr_number}",
            payload={"body": body},
        )

    def merge_pr(self, pr_number: int, *, commit_title: str | None = None) -> Any:
        return self._write(
            "merge_pr",
            "PUT",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls/{pr_number}/merge",
            payload={"commit_title": commit_title} if commit_title else {},
        )

    def enable_auto_merge(self, pr_number: int, *, merge_method: str = "SQUASH") -> Any:
        """Enable GitHub auto-merge so the forge merges the PR when its required
        checks (impl-judge + build + status) pass — the box stops self-merging
        (U4 judge-gated automerge: the judge CI check is the gate, no approval).

        Mode-gated like other writes: shadow -> dry-run record; spec-only ->
        blocked. Idempotent: an 'already enabled' GraphQL state is tolerated so a
        retry tick is safe. If GitHub reports the PR is already in 'clean status'
        (all checks green, nothing to wait for), auto-merge can't be armed, so we
        merge it directly instead.
        """
        self._sanitise_write("enable_auto_merge", {})
        mode = self.config.mode
        if mode == "shadow":
            result = DryRunResult(
                dry_run=True, operation="enable_auto_merge", payload={"pr": pr_number}
            )
            self.dry_run_records.append(result)
            return result
        if mode == "spec-only":
            raise PermissionError(
                "enable_auto_merge is not allowed when PIPELINE_MODE=spec-only"
            )
        pr = self.get_pr(pr_number)
        node_id = pr.get("node_id")
        if not node_id:
            raise RuntimeError(f"enable_auto_merge: no node_id for PR #{pr_number}")
        mutation = (
            "mutation($id: ID!, $m: PullRequestMergeMethod!) {"
            " enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: $m})"
            " { pullRequest { autoMergeRequest { enabledAt } } } }"
        )
        error_text = self._graphql(mutation, {"id": node_id, "m": merge_method})
        if error_text and "clean status" in error_text.lower():
            # Already mergeable, nothing pending to gate on -> merge now.
            log.info(
                "enable_auto_merge: PR #%s already clean — merging directly", pr_number
            )
            return self.merge_pr(pr_number)
        return None

    def _graphql(self, query: str, variables: dict[str, Any]) -> str | None:
        """POST a GraphQL query through ``_request`` (shared auth/timeout/session
        abstraction). Returns None on success, or the error message text when
        GitHub reports a tolerable/benign state (the caller decides what to do) —
        raises on a hard error. GraphQL returns HTTP 200 even on logical errors,
        so the error surface is the response body, not the status code."""
        body = self._request(
            "POST", "/graphql", json={"query": query, "variables": variables}
        )
        errors = body.get("errors")
        if not errors:
            return None
        text = "; ".join(str(error.get("message", error)) for error in errors)
        if any(token in text.lower() for token in ("already", "clean status")):
            log.info("graphql tolerated state: %s", text)
            return text
        raise RuntimeError(f"graphql error: {text}")

    def push_branch(
        self, clone_path: str, branch: str, *, spec_pr: bool = False
    ) -> Any:
        is_spec_branch = spec_pr or branch.startswith("bot/spec-")
        is_force_updated_bot_branch = is_spec_branch or branch.startswith("bot/impl-")
        payload = {"clone_path": clone_path, "branch": branch}
        if is_spec_branch:
            self._sanitise_spec_branch_files(Path(clone_path), branch)
        else:
            self._sanitise_spec_files(Path(clone_path))
        if self.config.mode == "shadow":
            return self._write(
                "push_branch", "GIT", "git push", payload=payload, spec_pr=spec_pr
            )
        if self.config.mode == "spec-only" and not spec_pr:
            return self._write(
                "push_branch", "GIT", "git push", payload=payload, spec_pr=spec_pr
            )
        # bot/spec-* and bot/impl-* branches are exclusively bot-owned and
        # re-authored from the base branch each pass. A prior remote branch can
        # diverge, so force-update the bot branch in place. (force-with-lease
        # would need a remote-tracking ref the shallow clone never fetched.)
        push_cmd = ["git", "push", "origin", branch]
        if is_force_updated_bot_branch:
            push_cmd.insert(2, "--force")
        try:
            completed = subprocess.run(
                push_cmd,
                cwd=clone_path,
                check=False,
                text=True,
                capture_output=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"git push timed out after {GIT_TIMEOUT_SECONDS}s")
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip() or f"git push failed for {branch}"
            )
        return {"ok": True, "stdout": completed.stdout}

    def _write(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any],
        spec_pr: bool = False,
    ) -> Any:
        self._sanitise_write(operation, payload)
        mode = self.config.mode
        if mode == "shadow":
            dry_payload = {"path": path, **payload}
            if operation == "create_pr":
                dry_payload["number"] = _synthetic_pr_number(payload)
            result = DryRunResult(
                dry_run=True, operation=operation, payload=dry_payload
            )
            self.dry_run_records.append(result)
            return result
        allowed_spec_pr_write = spec_pr and operation in {
            "push_branch",
            "create_pr",
            "remove_label",
            "add_label",
        }
        # The needs-human safety valve admits both adding the label and opening
        # a needs-human issue (escalate/create_needs_human/supervisor_dead/
        # circuit_breaker plan a creation, not a label add, when no issue exists).
        admits_needs_human = operation == "add_label" or operation == "create_issue"
        allowed_safety_write = admits_needs_human and "needs-human" in payload.get(
            "labels", []
        )
        if mode == "spec-only" and not (allowed_spec_pr_write or allowed_safety_write):
            raise PermissionError(
                f"{operation} is not allowed when PIPELINE_MODE=spec-only"
            )
        return self._request(method, path, json=payload)

    def _request(
        self, method: str, path: str, *, raw_text: bool = False, **kwargs: Any
    ) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Accept", "application/vnd.github+json")
        if self.config.wgmesh_bot_pat:
            headers.setdefault("Authorization", f"Bearer {self.config.wgmesh_bot_pat}")
        kwargs.setdefault("timeout", HTTP_TIMEOUT_SECONDS)
        try:
            response = self.session.request(
                method, f"{self.api_root}{path}", headers=headers, **kwargs
            )
        except requests.Timeout as exc:
            raise RuntimeError(
                f"GitHub request timed out after {kwargs['timeout']}s"
            ) from exc
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = (response.text or "")[:300]
            raise requests.HTTPError(f"{exc} :: {detail}", response=response) from None
        if raw_text:
            return response.text
        if response.text:
            return response.json()
        return {}

    def _sanitise_write(self, operation: str, payload: dict[str, Any]) -> None:
        if operation == "comment":
            self._require_clean("comment body", str(payload.get("body", "")))
        elif operation == "create_pr":
            self._require_clean("create_pr title", str(payload.get("title", "")))
            self._require_clean("create_pr body", str(payload.get("body", "")))
        elif operation == "create_issue":
            self._require_clean("create_issue title", str(payload.get("title", "")))
            self._require_clean("create_issue body", str(payload.get("body", "")))
        elif operation == "update_pr":
            self._require_clean("update_pr body", str(payload.get("body", "")))
        elif operation == "dispatch_workflow":
            # workflow_dispatch inputs can carry free text (e.g. a self-heal
            # idle reason) that lands in a triggered run — gate every value.
            for key, value in (payload.get("inputs") or {}).items():
                self._require_clean(f"dispatch_workflow input {key}", str(value))

    def _sanitise_spec_files(self, clone_path: Path) -> None:
        specs_dir = clone_path / "specs"
        if not specs_dir.exists():
            return
        for spec in sorted(specs_dir.glob("issue-*-spec.md")):
            self._require_clean(str(spec.relative_to(clone_path)), spec.read_text())

    def _sanitise_spec_branch_files(self, clone_path: Path, branch: str) -> None:
        expected_spec = _expected_spec_path(branch)
        if expected_spec is None:
            raise SanitiseError(
                f"cannot infer expected spec file from branch: {branch}"
            )
        if not (clone_path / expected_spec).is_file():
            if self.config.mode == "shadow":
                self._sanitise_spec_files(clone_path)
                return
            raise SanitiseError(f"expected spec file missing: {expected_spec}")

        changed_files = self._changed_files(clone_path)
        if not changed_files:
            raise SanitiseError(f"no changed files found for spec branch: {branch}")
        if expected_spec not in changed_files:
            raise SanitiseError(f"expected spec file not changed: {expected_spec}")

        for relative_path in sorted(changed_files):
            path = clone_path / relative_path
            if not path.is_file():
                continue
            try:
                text = path.read_text()
            except UnicodeDecodeError as exc:
                raise SanitiseError(
                    f"cannot sanitise non-text file: {relative_path}"
                ) from exc
            self._require_clean(relative_path, text)

    def _changed_files(self, clone_path: Path) -> set[str]:
        if not (clone_path / ".git").exists():
            return {
                path.relative_to(clone_path).as_posix()
                for path in clone_path.rglob("*")
                if path.is_file() and ".git" not in path.relative_to(clone_path).parts
            }

        changed: set[str] = set()
        for args in (
            ("diff", "--cached", "--name-only", "--diff-filter=ACMRT"),
            ("diff", "--name-only", "--diff-filter=ACMRT"),
            ("ls-files", "--others", "--exclude-standard"),
        ):
            changed.update(self._git_lines(clone_path, *args))

        base = self._merge_base(clone_path)
        if base is not None:
            changed.update(
                self._git_lines(
                    clone_path,
                    "diff",
                    "--name-only",
                    "--diff-filter=ACMRT",
                    f"{base}..HEAD",
                )
            )
        else:
            changed.update(
                self._git_lines(
                    clone_path,
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "--diff-filter=ACMRT",
                    "-r",
                    "HEAD",
                )
            )
        return changed

    def _merge_base(self, clone_path: Path) -> str | None:
        for base in ("origin/main", "main"):
            completed = self._git(clone_path, "merge-base", base, "HEAD")
            if completed.returncode == 0 and completed.stdout.strip():
                return completed.stdout.strip()
        return None

    def _git_lines(self, clone_path: Path, *args: str) -> set[str]:
        completed = self._git(clone_path, *args)
        if completed.returncode != 0:
            return set()
        return {line.strip() for line in completed.stdout.splitlines() if line.strip()}

    def _git(self, clone_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=clone_path,
                check=False,
                text=True,
                capture_output=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s"
            ) from exc

    def _require_clean(self, label: str, text: str) -> None:
        if self._sanitiser is not None:
            clean = self._sanitiser(text)
        else:
            clean = self._run_sanitise(text)
        if not clean:
            raise SanitiseError(f"sanitise failed for {label}")

    def _run_sanitise(self, text: str) -> bool:
        if not SANITISE_SCRIPT.exists():
            if self.config.mode == "shadow":
                return True
            raise SanitiseError(f"sanitise script missing: {SANITISE_SCRIPT}")
        try:
            completed = subprocess.run(
                [str(SANITISE_SCRIPT)],
                input=text,
                text=True,
                capture_output=True,
                check=False,
                timeout=SANITISE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return False
        return completed.returncode == 0


def _parse_issue(item: dict[str, Any]) -> GitHubIssue:
    labels = tuple(
        label["name"] if isinstance(label, dict) else str(label)
        for label in item.get("labels", [])
    )
    return GitHubIssue(
        number=int(item["number"]),
        title=str(item["title"]),
        labels=labels,
        state=str(item.get("state", "open")),
        pull_request=item.get("pull_request"),
    )


def _synthetic_pr_number(payload: dict[str, Any]) -> int:
    for field in ("head", "title"):
        digits = "".join(ch for ch in str(payload.get(field, "")) if ch.isdigit())
        if digits:
            return int(digits)
    return 1


def _expected_spec_path(branch: str) -> str | None:
    prefix = "bot/spec-"
    if not branch.startswith(prefix):
        return None
    issue_number = branch.removeprefix(prefix)
    if not issue_number.isdecimal():
        return None
    return f"specs/issue-{issue_number}-spec.md"
