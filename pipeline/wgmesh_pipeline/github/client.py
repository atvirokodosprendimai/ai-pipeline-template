from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.protocol import ForgeIssue


API_ROOT = "https://api.github.com"
SANITISE_SCRIPT = Path(__file__).resolve().parents[3] / "company" / "scripts" / "sanitise.sh"
GIT_TIMEOUT_SECONDS = 120
HTTP_TIMEOUT_SECONDS = 30
SANITISE_TIMEOUT_SECONDS = 120
Sanitiser = Callable[[str], bool]


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
        return [_parse_issue(item) for item in data]

    def list_open_issues(self) -> list[GitHubIssue]:
        data = self._request(
            "GET",
            f"/repos/{self.config.owner}/{self.config.repo}/issues",
            params={"state": "open"},
        )
        # GitHub's issues endpoint returns pull requests too (they carry a
        # "pull_request" key). Skip them — reconciling the box's own spec PRs
        # as issues caused a runaway: spec-of-spec PRs with exploding chained
        # titles (bug #11).
        return [_parse_issue(item) for item in data if "pull_request" not in item]

    def get_pr(self, number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self.config.owner}/{self.config.repo}/pulls/{number}")

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
        pattern = re.compile(
            rf"^(?:impl|spec|fix): (?:Issue #{issue_number}(?!\w)|.*\(Issue #{issue_number}\)\s*$)"
        )
        items = data.get("items") or []
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

    def remove_label(self, issue_number: int, label: str, *, spec_pr: bool = False) -> Any:
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

    def pr_checks_green(self, pr_number: int) -> bool:
        """All check runs on the PR head completed successfully. No checks at
        all counts as NOT green — fail closed."""
        pr = self.get_pr(pr_number)
        sha = (pr.get("head") or {}).get("sha")
        if not sha:
            return False
        data = self._request(
            "GET",
            f"/repos/{self.config.owner}/{self.config.repo}/commits/{sha}/check-runs",
            params={"per_page": 100},
        )
        runs = data.get("check_runs") or []
        if not runs:
            return False
        ok = {"success", "neutral", "skipped"}
        return all(
            run.get("status") == "completed" and run.get("conclusion") in ok for run in runs
        )

    def list_pr_approvals(self, pr_number: int) -> list[str]:
        """Logins whose LATEST review on the PR is an approval."""
        reviews = self._request(
            "GET",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls/{pr_number}/reviews",
            params={"per_page": 100},
        )
        latest: dict[str, str] = {}
        for review in reviews or []:
            login = str(((review.get("user") or {}).get("login")) or "")
            state = str(review.get("state") or "")
            if login and state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                latest[login] = state
        return [login for login, state in latest.items() if state == "APPROVED"]

    def can_review(self) -> bool:
        return bool(self.config.reviewer_pat)

    def approve_pr(self, pr_number: int) -> Any:
        """Approve as the REVIEWER identity — a distinct principal from the
        author bot. Approving with the author credential 422s on GitHub
        ('Can not approve your own pull request') and would defeat the
        distinct-principal gate anyway."""
        if not self.config.reviewer_pat:
            raise RuntimeError("approve_pr requires WGMESH_REVIEWER_PAT (reviewer identity)")
        if self.config.mode == "shadow":
            result = DryRunResult(
                dry_run=True, operation="approve_pr", payload={"pr": pr_number, "event": "APPROVE"}
            )
            self.dry_run_records.append(result)
            return result
        if self.config.mode == "spec-only":
            raise PermissionError("approve_pr is not allowed when PIPELINE_MODE=spec-only")
        return self._request(
            "POST",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls/{pr_number}/reviews",
            json={"event": "APPROVE"},
            headers={"Authorization": f"Bearer {self.config.reviewer_pat}"},
        )

    def push_branch(self, clone_path: str, branch: str, *, spec_pr: bool = False) -> Any:
        is_spec_branch = spec_pr or branch.startswith("bot/spec-")
        is_force_updated_bot_branch = is_spec_branch or branch.startswith("bot/impl-")
        payload = {"clone_path": clone_path, "branch": branch}
        if is_spec_branch:
            self._sanitise_spec_branch_files(Path(clone_path), branch)
        else:
            self._sanitise_spec_files(Path(clone_path))
        if self.config.mode == "shadow":
            return self._write("push_branch", "GIT", "git push", payload=payload, spec_pr=spec_pr)
        if self.config.mode == "spec-only" and not spec_pr:
            return self._write("push_branch", "GIT", "git push", payload=payload, spec_pr=spec_pr)
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
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"git push timed out after {GIT_TIMEOUT_SECONDS}s")
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"git push failed for {branch}")
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
            result = DryRunResult(dry_run=True, operation=operation, payload=dry_payload)
            self.dry_run_records.append(result)
            return result
        allowed_spec_pr_write = spec_pr and operation in {"push_branch", "create_pr", "remove_label", "add_label"}
        allowed_safety_write = operation == "add_label" and "needs-human" in payload.get("labels", [])
        if mode == "spec-only" and not (allowed_spec_pr_write or allowed_safety_write):
            raise PermissionError(f"{operation} is not allowed when PIPELINE_MODE=spec-only")
        return self._request(method, path, json=payload)

    def _request(self, method: str, path: str, *, raw_text: bool = False, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Accept", "application/vnd.github+json")
        if self.config.wgmesh_bot_pat:
            headers.setdefault("Authorization", f"Bearer {self.config.wgmesh_bot_pat}")
        kwargs.setdefault("timeout", HTTP_TIMEOUT_SECONDS)
        try:
            response = self.session.request(method, f"{self.api_root}{path}", headers=headers, **kwargs)
        except requests.Timeout as exc:
            raise RuntimeError(f"GitHub request timed out after {kwargs['timeout']}s") from exc
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
        elif operation == "update_pr":
            self._require_clean("update_pr body", str(payload.get("body", "")))

    def _sanitise_spec_files(self, clone_path: Path) -> None:
        specs_dir = clone_path / "specs"
        if not specs_dir.exists():
            return
        for spec in sorted(specs_dir.glob("issue-*-spec.md")):
            self._require_clean(str(spec.relative_to(clone_path)), spec.read_text())

    def _sanitise_spec_branch_files(self, clone_path: Path, branch: str) -> None:
        expected_spec = _expected_spec_path(branch)
        if expected_spec is None:
            raise SanitiseError(f"cannot infer expected spec file from branch: {branch}")
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
                raise SanitiseError(f"cannot sanitise non-text file: {relative_path}") from exc
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
            changed.update(self._git_lines(clone_path, "diff", "--name-only", "--diff-filter=ACMRT", f"{base}..HEAD"))
        else:
            changed.update(self._git_lines(clone_path, "diff-tree", "--no-commit-id", "--name-only", "--diff-filter=ACMRT", "-r", "HEAD"))
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
            raise RuntimeError(f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s") from exc

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
    labels = tuple(label["name"] if isinstance(label, dict) else str(label) for label in item.get("labels", []))
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
