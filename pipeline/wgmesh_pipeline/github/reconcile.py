from __future__ import annotations

import logging
from dataclasses import dataclass

from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue
from wgmesh_pipeline.state.store import StateStore

log = logging.getLogger(__name__)


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
            # Resolved-guard: only for issues the store has never seen (fresh
            # or post-reset_queue — the path that wipes Turso state). An issue
            # with a live stage is mid-flight; its merged *spec* PR must not
            # mark it resolved, or every impl is abandoned after spec merge.
            if current_stage is None:
                try:
                    resolved = client.has_merged_resolution_pr(issue.number)
                except Exception as exc:
                    # Skip this issue for the tick: aborting the whole
                    # reconcile on a search rate-limit stalls every claim,
                    # and failing open re-queues a resolved issue — the bug
                    # this guard exists to stop.
                    log.warning("reconcile: resolution lookup failed for #%s: %s", issue.number, exc)
                    continue
                if resolved:
                    if "needs-rework" not in labels:
                        store.upsert_issue(issue.number, issue.title, stage="merged", status=issue.state)
                        merged += 1
                        continue
                    if client.find_open_pr_number(f"bot/impl-{issue.number}") is not None:
                        continue
                    store.upsert_issue(issue.number, issue.title, stage="queued", status="open")
                    client.remove_label(issue.number, "needs-rework", spec_pr=True)
                    queued += 1
                    continue
            store.upsert_issue(issue.number, issue.title, stage=current_stage or "queued", status="open")
    return ReconcileResult(seen=seen, queued=queued, escalated=escalated, merged=merged)


def _current_stage(store: StateStore, number: int) -> str | None:
    try:
        return store.get_issue(number).stage
    except KeyError:
        return None
