from __future__ import annotations

from dataclasses import dataclass

from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue
from wgmesh_pipeline.state.store import StateStore


TERMINAL_STAGES = {"merged", "escalated", "failed"}
MERGED_LABELS = {"merged", "completed", "done", "impl-merged"}


@dataclass(frozen=True)
class ReconcileResult:
    seen: int
    queued: int
    escalated: int
    merged: int


def reconcile_issues(client: GitHubClient, store: StateStore) -> ReconcileResult:
    seen = queued = escalated = merged = 0
    for issue in client.list_open_issues():
        seen += 1
        labels = set(issue.labels)
        current_stage = _current_stage(store, issue.number)
        if current_stage in TERMINAL_STAGES:
            continue

        if issue.state == "closed" or labels & MERGED_LABELS:
            store.upsert_issue(issue.number, issue.title, stage="merged", status="closed")
            merged += 1
        elif "needs-human" in labels:
            store.upsert_issue(issue.number, issue.title, stage="escalated", status="open")
            escalated += 1
        elif "needs-triage" in labels or "copilot-triaging" in labels:
            if current_stage is None:
                store.upsert_issue(issue.number, issue.title, stage="queued", status="open")
                queued += 1
            elif current_stage != "queued" and "needs-triage" in labels:
                # spec_pr=True: this needs-triage cleanup is a legitimate
                # spec-lane label write (same as spec_pr_node). Without the flag
                # the spec-only write-gate raises PermissionError, which crashed
                # reconcile every tick and stalled the whole loop.
                client.remove_label(issue.number, "needs-triage", spec_pr=True)
        else:
            store.upsert_issue(issue.number, issue.title, stage=current_stage or "queued", status="open")
    return ReconcileResult(seen=seen, queued=queued, escalated=escalated, merged=merged)


def _current_stage(store: StateStore, number: int) -> str | None:
    try:
        return store.get_issue(number).stage
    except KeyError:
        return None
