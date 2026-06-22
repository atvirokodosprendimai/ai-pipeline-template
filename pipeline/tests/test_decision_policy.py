"""Decision-lane approval-threshold policy (U3) — the consent gate.

Test-first: this is the safety brake on the capability ladder, so every tier /
count / vote combination is pinned, including the intended N=2 unanimous stall.
"""

from __future__ import annotations

import pytest

from wgmesh_pipeline.decision_lane.policy import (
    DANGEROUS,
    ROUTINE,
    is_approved,
    required_approvals,
)


def test_routine_needs_one_regardless_of_count() -> None:
    assert required_approvals(ROUTINE, 2) == 1
    assert required_approvals(ROUTINE, 5) == 1


def test_dangerous_needs_all_current_cofounders() -> None:
    assert required_approvals(DANGEROUS, 2) == 2  # unanimous at N=2
    assert required_approvals(DANGEROUS, 5) == 5


def test_dangerous_floors_at_one() -> None:
    assert required_approvals(DANGEROUS, 0) == 1


def test_unknown_tier_raises_never_lowers_bar() -> None:
    with pytest.raises(ValueError, match="unknown decision risk tier"):
        required_approvals("freebie", 2)


def test_is_approved_true_at_threshold_false_below() -> None:
    assert is_approved(1, ROUTINE, 2) is True
    assert is_approved(0, ROUTINE, 2) is False


def test_is_approved_dangerous_n2_one_vote_is_the_intended_stall() -> None:
    # The point of the dangerous tier at N=2: one founder is not enough.
    assert is_approved(1, DANGEROUS, 2) is False
    assert is_approved(2, DANGEROUS, 2) is True
