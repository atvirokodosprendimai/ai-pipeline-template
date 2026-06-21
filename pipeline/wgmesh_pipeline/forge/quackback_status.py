"""Quackback status vocabulary + the box-settable allowlist (KTD9).

Decision-status authority is the founder's: the box must never author
``Accepted for Build`` / ``Rejected`` (or any other decision status). Server-side
enforcement via a least-privilege key is the real guard, but Quackback keys are
all-or-nothing — so this **client-side allowlist is the sole guard** and is
enforced locally in ``QuackbackForge.set_status`` (KTD9, revised). The set is the
only statuses the box flips as it drives execution milestones.
"""

from __future__ import annotations

# The only statuses the box itself may set (execution-milestone mirroring).
# Everything else — Open for Vote, Needs Refinement, Accepted for Build,
# Rejected, Cancelled — is a human decision the box must never author.
BOX_SETTABLE_STATUSES: frozenset[str] = frozenset(
    {"Building", "Ready for Review", "Shipped"}
)

# The single decision status that gates ingest (the front gate). Posts in this
# status are the box's work queue.
ACCEPTED_FOR_BUILD = "Accepted for Build"

# KTD4 milestone map: the box's internal execution stage (state/store.py
# ALLOWED_TRANSITIONS) → the Quackback status it mirrors the post to. Only stages
# *past* ``queued`` flip the post (first real claim → Building); the review
# milestone (``reviewed``/``awaiting_merge``) → Ready for Review; terminal
# ``merged`` (real ``pr.merged``) → Shipped. ``queued`` and the terminal-error
# stages (``escalated``/``failed``) map to nothing — the box does not flip on
# them. U6 wires the triggers; this dict is the single source of truth. Every
# value is box-settable (asserted in tests), so the allowlist never blocks a
# legitimate milestone flip.
STAGE_TO_STATUS: dict[str, str] = {
    "triaged": "Building",
    "specced": "Building",
    "spec_opened": "Building",
    "spec_ready": "Building",
    "implemented": "Building",
    "reviewed": "Ready for Review",
    "awaiting_merge": "Ready for Review",
    "merged": "Shipped",
}


def is_box_settable(status: str) -> bool:
    return status in BOX_SETTABLE_STATUSES


def status_for_stage(stage: str) -> str | None:
    """The Quackback status to mirror for a store stage, or ``None`` if the box
    does not flip the post on that stage (``queued``/``escalated``/``failed``)."""
    return STAGE_TO_STATUS.get(stage)
