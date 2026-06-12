"""Distinct-principal merge gate.

The box is an independent developer: its PRs merge only when CI is green AND
a principal other than the PR author has approved. The box never holds admin
bypass. When the box has a reviewer credential (a second identity), it may
self-serve the approval through that identity; with no reviewer credential
the PR escalates instead of merging — fail closed, never fail open.

Born from a live failure: the wgmesh auto-merge lane approved with the same
app identity that authored the PR and got 422 "Can not approve your own
pull request" (2026-06-11).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from wgmesh_pipeline.forge.box_ci import BoxCiResult

log = logging.getLogger(__name__)


class _ReviewSurface(Protocol):
    def get_pr(self, number: int) -> dict[str, Any]: ...

    def pr_checks_green(self, pr_number: int) -> bool: ...

    def list_pr_approvals(self, pr_number: int) -> list[str]: ...

    def can_review(self) -> bool: ...

    def approve_pr(self, pr_number: int) -> Any: ...


@dataclass(frozen=True)
class MergeReadiness:
    ready: bool
    reasons: tuple[str, ...]


def ensure_mergeable(
    client: _ReviewSurface,
    pr_number: int,
    *,
    ci_verdict: BoxCiResult | None = None,
) -> MergeReadiness:
    reasons: list[str] = []

    # Cutover U9: bot PRs are CI'd on the box itself; when a box-run verdict
    # is supplied it IS the CI signal and the Actions check-runs API is never
    # polled. Without a verdict (external PRs / not-yet-cutover configs) the
    # host's check-runs remain the source.
    if ci_verdict is not None:
        if not ci_verdict.green:
            reasons.append("ci not green")
            reasons.extend(ci_verdict.failures)
    elif not client.pr_checks_green(pr_number):
        reasons.append("ci not green")

    pr = client.get_pr(pr_number)
    author = str(((pr.get("user") or {}).get("login")) or "")
    approvals = client.list_pr_approvals(pr_number)
    has_distinct = any(login and login != author for login in approvals)

    if not has_distinct:
        if reasons:
            # Don't burn a reviewer approval on a red build — it would go
            # stale by the time CI is fixed and pushed.
            reasons.append("no distinct-principal approval (deferred while ci not green)")
        elif client.can_review():
            # The reviewer credential is a separate principal from the author
            # bot by configuration; its approval satisfies the gate. A failed
            # approval (422 same-identity misconfig, expired PAT) must become
            # a readiness reason, not an exception — otherwise it bypasses
            # the needs-human escalation path and strands the issue mid-merge.
            try:
                client.approve_pr(pr_number)
            except Exception as exc:
                log.warning("merge gate: reviewer approval failed for PR #%s: %s", pr_number, exc)
                reasons.append(f"reviewer approval failed: {exc}")
        else:
            reasons.append("no distinct-principal approval and no reviewer credential")

    return MergeReadiness(ready=not reasons, reasons=tuple(reasons))
