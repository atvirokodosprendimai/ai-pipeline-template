"""Decision-lane orchestrator (U7) — the consent loop, Phase 1.

One cycle: ingest the founder-flagged decision posts (``Needs Refinement``), and
for each, take exactly one step:

  - **no proposal yet** → draft one (run the recipe) and post it as a comment;
  - **a new co-founder comment** (and under the iteration cap) → revise;
  - **approval threshold met** → open the final proposal post + retire the
    discussion post;
  - otherwise → no-op.

KTD9 holds: the box drives comments / a new post / reads votes — it never sets a
decision status. KTD7: execution stops at the final proposal post (no self-mod,
no spend in Phase 1).

The cycle is **plan-then-maybe-execute**: it computes a list of ``PlannedAction``
and, only when ``live`` is true, performs them through the forge (sanitise-walled).
In shadow it returns the plan and writes nothing — identical-path shadow, like the
observation module. The proposal text is produced by an injected ``proposal_fn``
so the recipe runner is a seam the tests replace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from wgmesh_pipeline.decision_lane.comments import (
    is_unprocessed,
    latest_cofounder_comment,
)
from wgmesh_pipeline.decision_lane.policy import ROUTINE, is_approved

log = logging.getLogger("wgmesh_pipeline.decision_lane")

# Phase 1 is read-only: every proposal is routine (no self-mod / spend exists yet).
PHASE1_RISK_TIER = ROUTINE

ProposalFn = Callable[[dict[str, Any], dict[str, Any] | None], str]
"""(post, latest_cofounder_comment_or_None) -> proposal markdown."""


class _Forge(Protocol):
    def list_decision_asks(self) -> list[dict[str, Any]]: ...
    def list_post_comments(self, post_id: str) -> list[dict[str, Any]]: ...
    def post_vote_count(self, post_id: str) -> int: ...
    def post_proposal_comment(self, post_id: str, body: str) -> Any: ...
    def open_final_proposal(self, title: str, body: str) -> dict[str, Any]: ...
    def mark_superseded(self, post_id: str, final_ref: str) -> Any: ...


@dataclass(frozen=True)
class PlannedAction:
    """One step the lane decided to take for one post."""

    post_id: str
    kind: str  # "draft" | "revise" | "finalize" | "noop"
    detail: str = ""


@dataclass(frozen=True)
class DecisionCycleResult:
    seen: int
    planned: tuple[PlannedAction, ...]
    executed: int


def run_decision_cycle(
    forge: _Forge,
    store: Any,
    proposal_fn: ProposalFn,
    *,
    bot_author: str,
    cofounder_count: int,
    max_iterations: int,
    live: bool,
) -> DecisionCycleResult:
    """Run one decision-lane cycle. Plans an action per post; executes only when
    ``live``. Never raises into the loop on a single bad post — logs and continues
    (batch-resilient, like the executor)."""
    asks = forge.list_decision_asks()
    planned: list[PlannedAction] = []
    executed = 0

    for post in asks:
        post_id = str(post.get("id") or "")
        if not post_id:
            continue
        try:
            action = _plan_one(
                forge, store, post, bot_author, max_iterations, cofounder_count
            )
            planned.append(action)
            if live and action.kind != "noop":
                _execute_one(forge, store, post, action, proposal_fn, bot_author)
                executed += 1
        except Exception:  # batch-resilient — one bad post must not kill the cycle
            log.exception("decision lane: post %s failed; continuing", post_id)

    return DecisionCycleResult(
        seen=len(asks), planned=tuple(planned), executed=executed
    )


def _plan_one(
    forge: _Forge,
    store: Any,
    post: dict[str, Any],
    bot_author: str,
    max_iterations: int,
    cofounder_count: int,
) -> PlannedAction:
    post_id = str(post["id"])
    state = store.get_decision_state(post_id)

    if state is None:
        return PlannedAction(post_id, "draft", "no proposal yet")

    comments = forge.list_post_comments(post_id)
    latest = latest_cofounder_comment(comments, bot_author)
    if is_unprocessed(latest, state["last_comment_id"]):
        if state["iterations"] >= max_iterations:
            return PlannedAction(post_id, "noop", "max iterations reached")
        return PlannedAction(post_id, "revise", "new co-founder comment")

    votes = forge.post_vote_count(post_id)
    if is_approved(votes, PHASE1_RISK_TIER, cofounder_count):
        return PlannedAction(post_id, "finalize", f"approved ({votes} votes)")
    return PlannedAction(post_id, "noop", "awaiting feedback or votes")


def _execute_one(
    forge: _Forge,
    store: Any,
    post: dict[str, Any],
    action: PlannedAction,
    proposal_fn: ProposalFn,
    bot_author: str,
) -> None:
    post_id = action.post_id
    if action.kind in ("draft", "revise"):
        latest = (
            latest_cofounder_comment(forge.list_post_comments(post_id), bot_author)
            if action.kind == "revise"
            else None
        )
        body = proposal_fn(post, latest)
        forge.post_proposal_comment(post_id, body)
        store.record_decision_proposal(
            post_id, last_comment_id=(latest.get("id") if latest else None)
        )
    elif action.kind == "finalize":
        title = f"[Decided] {post.get('title', '')}"
        body = proposal_fn(post, None)
        final = forge.open_final_proposal(title, body)
        forge.mark_superseded(post_id, str(final.get("id") or ""))
