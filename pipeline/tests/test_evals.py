from __future__ import annotations

import pytest

from evals.eval_gate import EvalFailure, broken_gate_always_merge, evaluate_gate, load_cases
from evals.eval_spec import spec_is_structurally_ok
from evals.eval_trajectory import TrajectoryEvalFailure, assert_never_skips_review


def test_deliberately_broken_gate_fails_golden_eval() -> None:
    cases = load_cases("pipeline/evals/datasets/gate_golden.jsonl")

    with pytest.raises(EvalFailure, match="escalate_recall"):
        evaluate_gate(cases, gate_func=broken_gate_always_merge)


def test_spec_eval_flags_missing_proposed_approach() -> None:
    spec = "## Problem\nMissing plan\n\n## Acceptance Criteria\n- clear enough\n"

    assert spec_is_structurally_ok(spec) is False


def test_trajectory_eval_fails_trace_that_skips_review() -> None:
    with pytest.raises(TrajectoryEvalFailure, match="without review"):
        assert_never_skips_review(["triage", "spec", "implement", "gate", "merge"])

