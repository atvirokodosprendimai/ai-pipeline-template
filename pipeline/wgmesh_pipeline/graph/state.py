from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue


Classification = Literal["fix", "feature", "wont-do", "needs-info"]
Decision = Literal["merge", "escalate"]


class GraphState(TypedDict, total=False):
    issue: GitHubIssue
    issue_body: str
    classification: Classification
    classification_override: Classification
    spec_path: str
    spec_branch: str
    spec_pr: int
    diff: str
    changed_files: list[str]
    risk_tier: str
    risk_reasons: list[str]
    retryable: bool
    review_findings: list[dict[str, Any]]
    tests_passed: bool
    sanitise_ok: bool
    decision: Decision
    escalation_tier: int
    escalation_attempts: int
    escalation_history: list[int]
    visited: list[str]
    github: GitHubClient
    repo_path: str | Path
    goose_runner: Any
    impl_pr: int
    config: Config
    # Surface gate (keeps service/unclassified issues out of the wgmesh builder).
    # Declared so the langgraph StateGraph propagates them between nodes — an
    # undeclared channel is silently dropped, which would make route_after_surface_gate
    # see no verdict and escalate every issue.
    surface: str
    surface_verdict: str
    surface_classifier: Any
