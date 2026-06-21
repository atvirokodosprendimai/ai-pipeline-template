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


def is_box_settable(status: str) -> bool:
    return status in BOX_SETTABLE_STATUSES
