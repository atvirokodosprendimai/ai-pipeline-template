from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from wgmesh_pipeline.config import Config


API_ROOT = "https://api.github.com"
SANITISE_SCRIPT = Path(__file__).resolve().parents[3] / "company" / "scripts" / "sanitise.sh"
GIT_TIMEOUT_SECONDS = 120
HTTP_TIMEOUT_SECONDS = 30
SANITISE_TIMEOUT_SECONDS = 120
Sanitiser = Callable[[str], bool]


class SanitiseError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubIssue:
    number: int
    title: str
    labels: tuple[str, ...]
    state: str
    pull_request: dict[str, Any] | None = None


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
        return [_parse_issue(item) for item in data]

    def get_pr(self, number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self.config.owner}/{self.config.repo}/pulls/{number}")

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
            spec_pr=spec_pr or title.startswith("spec: Issue #"),
        )

    def merge_pr(self, pr_number: int, *, commit_title: str | None = None) -> Any:
        return self._write(
            "merge_pr",
            "PUT",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls/{pr_number}/merge",
            payload={"commit_title": commit_title} if commit_title else {},
        )

    def push_branch(self, clone_path: str, branch: str, *, spec_pr: bool = False) -> Any:
        payload = {"clone_path": clone_path, "branch": branch}
        self._sanitise_spec_files(Path(clone_path))
        if self.config.mode == "shadow":
            return self._write("push_branch", "GIT", "git push", payload=payload, spec_pr=spec_pr)
        if self.config.mode == "spec-only" and not spec_pr:
            return self._write("push_branch", "GIT", "git push", payload=payload, spec_pr=spec_pr)
        try:
            completed = subprocess.run(
                ["git", "push", "origin", branch],
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
        if mode == "spec-only" and not (spec_pr and operation in {"push_branch", "create_pr", "remove_label", "add_label"}):
            raise PermissionError(f"{operation} is not allowed when PIPELINE_MODE=spec-only")
        return self._request(method, path, json=payload)

    def _request(self, method: str, path: str, *, raw_text: bool = False, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Accept", "application/vnd.github+json")
        if self.config.wgmesh_bot_pat:
            headers["Authorization"] = f"Bearer {self.config.wgmesh_bot_pat}"
        kwargs.setdefault("timeout", HTTP_TIMEOUT_SECONDS)
        try:
            response = self.session.request(method, f"{self.api_root}{path}", headers=headers, **kwargs)
        except requests.Timeout as exc:
            raise RuntimeError(f"GitHub request timed out after {kwargs['timeout']}s") from exc
        response.raise_for_status()
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

    def _sanitise_spec_files(self, clone_path: Path) -> None:
        specs_dir = clone_path / "specs"
        if not specs_dir.exists():
            return
        for spec in sorted(specs_dir.glob("issue-*-spec.md")):
            self._require_clean(str(spec.relative_to(clone_path)), spec.read_text())

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
