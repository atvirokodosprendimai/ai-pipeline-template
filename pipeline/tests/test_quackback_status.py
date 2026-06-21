"""U3: status vocabulary + KTD4 milestone map."""

from __future__ import annotations

from wgmesh_pipeline.forge.quackback_status import (
    ACCEPTED_FOR_BUILD,
    BOX_SETTABLE_STATUSES,
    STAGE_TO_STATUS,
    is_box_settable,
    status_for_stage,
)


def test_box_settable_allowlist_is_exactly_the_three_milestones() -> None:
    assert BOX_SETTABLE_STATUSES == frozenset(
        {"Building", "Ready for Review", "Shipped"}
    )


def test_decision_statuses_are_not_box_settable() -> None:
    # The box must never author a decision status (KTD9).
    for decision in (ACCEPTED_FOR_BUILD, "Rejected", "Cancelled", "Needs Refinement", "Open for Vote"):
        assert not is_box_settable(decision)


def test_every_mapped_status_is_box_settable() -> None:
    # A legitimate milestone flip must never be blocked by the allowlist.
    for status in STAGE_TO_STATUS.values():
        assert is_box_settable(status)


def test_stage_milestones_map_per_ktd4() -> None:
    # Past queued → Building.
    for stage in ("triaged", "specced", "spec_opened", "spec_ready", "implemented"):
        assert status_for_stage(stage) == "Building"
    # Review milestone → Ready for Review.
    assert status_for_stage("reviewed") == "Ready for Review"
    assert status_for_stage("awaiting_merge") == "Ready for Review"
    # Terminal merged → Shipped.
    assert status_for_stage("merged") == "Shipped"


def test_non_mirroring_stages_map_to_none() -> None:
    # queued (pre-claim) and terminal-error stages do not flip the post.
    for stage in ("queued", "escalated", "failed", "unknown"):
        assert status_for_stage(stage) is None
