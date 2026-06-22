"""Decision-lane comment author-distinction (U4).

The lane re-drafts a proposal only on a NEW co-founder comment — never on its own
comment, never twice on the same one. ``isTeamMember`` marks workspace members
(co-founders); the bot key is also a member, so its own comments are excluded by
``authorName``. Pure functions over the raw comment dicts from
``QuackbackClient.list_comments``.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def latest_cofounder_comment(
    comments: Sequence[Mapping[str, Any]], bot_author: str
) -> dict[str, Any] | None:
    """The newest co-founder comment (team member, not the box), or ``None``.

    A co-founder comment is ``isTeamMember`` true AND ``authorName`` not the bot's
    — the bot is itself a team member, so the name is what separates its own
    comments from the founders'."""
    cofounder = [
        c
        for c in comments
        if c.get("isTeamMember") and str(c.get("authorName")) != bot_author
    ]
    if not cofounder:
        return None
    return dict(max(cofounder, key=lambda c: str(c.get("createdAt") or "")))


def is_unprocessed(
    comment: Mapping[str, Any] | None, last_comment_id: str | None
) -> bool:
    """True iff ``comment`` exists and is newer than the last one the lane acted
    on — the signal to re-draft. Comparing the id (not the timestamp) makes it
    idempotent against a re-read of the same thread."""
    if comment is None:
        return False
    return str(comment.get("id")) != str(last_comment_id) if last_comment_id else True
