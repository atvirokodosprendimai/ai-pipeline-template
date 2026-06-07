from __future__ import annotations

from pathlib import Path

import pytest

from evals.eval_gate import (
    EvalFailure,
    broken_gate_always_merge,
    broken_gate_ignores_non_risk_guards,
    evaluate_gate,
    load_cases,
)
from evals.eval_spec import spec_is_structurally_ok
from evals.eval_trajectory import TrajectoryEvalFailure, assert_never_skips_review


GATE_GOLDEN = Path(__file__).resolve().parents[1] / "evals" / "datasets" / "gate_golden.jsonl"


def gate_cases() -> list[dict]:
    return load_cases(GATE_GOLDEN)


def test_deliberately_broken_gate_fails_golden_eval() -> None:
    cases = gate_cases()

    with pytest.raises(EvalFailure, match="escalate_recall"):
        evaluate_gate(cases, gate_func=broken_gate_always_merge)


def test_gate_eval_fails_gate_that_ignores_tests_sanitise_and_findings() -> None:
    cases = gate_cases()

    with pytest.raises(EvalFailure, match="tests-failed"):
        evaluate_gate(cases, gate_func=broken_gate_ignores_non_risk_guards)


def test_gate_eval_dataset_path_is_independent_of_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert gate_cases()[0]["id"] == "benign-docs"


def test_spec_eval_flags_missing_proposed_approach() -> None:
    spec = "## Problem\nMissing plan\n\n## Acceptance Criteria\n- clear enough\n"

    assert spec_is_structurally_ok(spec) is False


def test_trajectory_eval_fails_trace_that_skips_review() -> None:
    with pytest.raises(TrajectoryEvalFailure, match="without review"):
        assert_never_skips_review(["triage", "spec", "implement", "gate", "merge"])
