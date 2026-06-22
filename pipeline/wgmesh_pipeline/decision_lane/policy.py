"""Decision-lane approval-threshold policy (Phase 1).

The brake on the capability-acquisition ladder is co-founder consent. A proposal
executes only once it clears its approval threshold, and the threshold is
**risk-tiered**, not a flat quorum — a flat quorum is degenerate at the current
team size (2 co-founders):

  - ``routine`` (a cheap tool, a low-cost decision) → **1** approve-vote.
  - ``dangerous`` (self-modify the pipeline, spend over the configured line, rent
    a stranger) → **all current co-founders** (= 2 today; unanimous).

The threshold is expressed relative to the *current* co-founder count, so it
scales (1 / majority / all) as the team grows without a redesign. Phase 1 has no
dangerous actions — the lane is read-only and only produces the decided artifact —
so every Phase-1 caller passes ``routine`` and the gate is ``vote_count >= 1``.

Pure functions, no I/O: the count comes from the Quackback ``voteCount`` (the
private board means every voter is a co-founder, so the count is a sound proxy;
there is no voter list — ``GET /posts/{id}/votes`` is 404).
"""

from __future__ import annotations

ROUTINE = "routine"
DANGEROUS = "dangerous"
RISK_TIERS = frozenset({ROUTINE, DANGEROUS})


def required_approvals(risk_tier: str, cofounder_count: int) -> int:
    """How many approve-votes a proposal of ``risk_tier`` needs.

    ``routine`` → 1; ``dangerous`` → all current co-founders (at least 1). Raises
    on an unknown tier — a mis-typed tier must never silently lower the bar."""
    if risk_tier == ROUTINE:
        return 1
    if risk_tier == DANGEROUS:
        return max(1, int(cofounder_count))
    raise ValueError(f"unknown decision risk tier: {risk_tier!r}")


def is_approved(vote_count: int, risk_tier: str, cofounder_count: int) -> bool:
    """True iff ``vote_count`` meets the tier's threshold."""
    return int(vote_count) >= required_approvals(risk_tier, cofounder_count)
