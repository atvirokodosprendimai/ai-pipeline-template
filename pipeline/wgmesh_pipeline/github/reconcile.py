from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from wgmesh_pipeline.forge.protocol import Forge
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
    pruned: int = 0


def _label_write_best_effort(
    fn: Callable[..., object], *args: object, **kwargs: object
) -> None:
    """Labels are mirrors for humans, not gates — the store is authoritative.
    A failed label write must never block reconcile (telemetry-write lesson:
    side-channel writes stay off the convergence path)."""
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        log.warning(
            "label write failed (non-blocking): %s(%s): %s",
            getattr(fn, "__name__", fn),
            args,
            exc,
        )


def reconcile_issues(
    client: Forge,
    store: StateStore,
    *,
    resolution_lookup: Callable[[int], bool] | None = None,
) -> ReconcileResult:
    """resolution_lookup defaults to the forge's host API; main wires the
    git-first lookup (forge/gitfacts.py) so resolution is keyed on git facts
    with the host API as freshness fallback."""
    lookup = resolution_lookup or client.has_merged_resolution_pr
    seen = queued = escalated = merged = pruned = 0
    open_issue_numbers: set[int] = set()
    for issue in client.list_open_issues():
        seen += 1
        open_issue_numbers.add(issue.number)
        labels = set(issue.labels)
        current_stage = _current_stage(store, issue.number)
        if current_stage in TERMINAL_STAGES:
            if (
                current_stage == "escalated"
                and issue.state != "closed"
                and "needs-human" not in labels
                and labels & {"needs-triage", "copilot-triaging"}
            ):
                store.upsert_issue(
                    issue.number, issue.title, stage="queued", status="open"
                )
                queued += 1
            continue

        if issue.state == "closed" or labels & MERGED_LABELS:
            store.upsert_issue(
                issue.number, issue.title, stage="merged", status="closed"
            )
            merged += 1
        elif "needs-human" in labels:
            store.upsert_issue(
                issue.number, issue.title, stage="escalated", status="open"
            )
            escalated += 1
        elif "needs-triage" in labels or "copilot-triaging" in labels:
            if current_stage is None:
                store.upsert_issue(
                    issue.number, issue.title, stage="queued", status="open"
                )
                queued += 1
            elif current_stage != "queued" and "needs-triage" in labels:
                # spec_pr=True: this needs-triage cleanup is a legitimate
                # spec-lane label write (same as spec_pr_node). Without the flag
                # the spec-only write-gate raises PermissionError, which crashed
                # reconcile every tick and stalled the whole loop.
                _label_write_best_effort(
                    client.remove_label, issue.number, "needs-triage", spec_pr=True
                )
        else:
            # Resolved-guard: only for issues the store has never seen (fresh
            # or post-reset_queue — the path that wipes Turso state). An issue
            # with a live stage is mid-flight; its merged *spec* PR must not
            # mark it resolved, or every impl is abandoned after spec merge.
            if current_stage is None:
                try:
                    resolved = lookup(issue.number)
                except Exception as exc:
                    # Skip this issue for the tick: aborting the whole
                    # reconcile on a search rate-limit stalls every claim,
                    # and failing open re-queues a resolved issue — the bug
                    # this guard exists to stop.
                    log.warning(
                        "reconcile: resolution lookup failed for #%s: %s",
                        issue.number,
                        exc,
                    )
                    continue
                if resolved:
                    if "needs-rework" not in labels:
                        store.upsert_issue(
                            issue.number,
                            issue.title,
                            stage="merged",
                            status=issue.state,
                        )
                        merged += 1
                        continue
                    if (
                        client.find_open_pr_number(f"bot/impl-{issue.number}")
                        is not None
                    ):
                        continue
                    store.upsert_issue(
                        issue.number, issue.title, stage="queued", status="open"
                    )
                    _label_write_best_effort(
                        client.remove_label, issue.number, "needs-rework", spec_pr=True
                    )
                    queued += 1
                    continue
            store.upsert_issue(
                issue.number,
                issue.title,
                stage=current_stage or "queued",
                status="open",
            )
    for record in store.list_issues():
        if record.stage != "escalated" or record.status != "open":
            continue
        if record.number in open_issue_numbers:
            continue
        try:
            upstream = client.get_issue(record.number)
        except Exception as exc:
            log.warning("reconcile: get_issue failed for #%s: %s", record.number, exc)
            continue
        if upstream is None or upstream.state.lower() == "closed":
            store.set_stage(record.number, "merged", status="closed")
            pruned += 1
            log.info(
                "reconcile: pruned ghost escalation #%s (closed upstream)",
                record.number,
            )
    return ReconcileResult(
        seen=seen, queued=queued, escalated=escalated, merged=merged, pruned=pruned
    )


def reconcile_quackback(client: object, store: StateStore) -> ReconcileResult:
    """Quackback ingest (KTD3) — NO GitHub-label semantics.

    Upserts only ``Accepted for Build`` posts into the store at ``queued``, keyed
    on a store-backed ``(quackback_post_id, accept_marker)`` mapping. Idempotent
    and safe to retry every tick:

      - a transient API error propagates (fail-closed, KTD5) and the next tick
        re-ingests cleanly;
      - a partial page never double-ingests, because the mapping is keyed on
        ``(post_id, marker)`` — an already-seen marker is a no-op.

    ``accept_marker`` is the accepted post's ``updatedAt`` (KTD6/OQ2: no
    status_version field exists, so the accept-transition timestamp IS the
    marker; a re-accept advances it and re-queues the same number). Only the
    post TITLE is carried into the store (KTD10) — never the full body.
    """
    seen = queued = 0
    for post in client.list_accepted_posts():
        post_id = str(post.get("id") or "")
        if not post_id:
            continue
        marker = post.get("updatedAt")
        title = str(post.get("title", ""))
        number, fresh = store.map_quackback_post(post_id, marker)
        seen += 1
        if fresh:
            store.upsert_issue(
                number, title, stage="queued", status="open",
                body=_safe_brief(post, number),
            )
            queued += 1
    return ReconcileResult(seen=seen, queued=queued, escalated=0, merged=0)


def _safe_brief(post: dict, number: int) -> str:
    """The post body, sanitised, for the builder to spec from (KTD10 handled by
    the wall, not by dropping). A body that fails the sanitise wall degrades to
    empty — the issue still builds from its title — rather than leaking PII into
    a public spec/PR. The title is already sanitised at create time."""
    content = str(post.get("content") or "")
    if not content:
        return ""
    # Local import: keep the control-loop graph out of module-load import order.
    from wgmesh_pipeline.graph.nodes.review import run_sanitise

    if run_sanitise(content):
        return content
    log.warning(
        "quackback ingest #%s: post body failed the sanitise wall — "
        "building from title only (brief dropped)",
        number,
    )
    return ""


def _current_stage(store: StateStore, number: int) -> str | None:
    try:
        return store.get_issue(number).stage
    except KeyError:
        return None
