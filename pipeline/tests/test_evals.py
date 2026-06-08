from __future__ import annotations

from pathlib import Path

import pytest

from evals import run_evals
from evals.eval_gate import (
    EvalFailure,
    GateMetrics,
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


def write_eval_dataset(tmp_path: Path, gate_lines: list[str]) -> Path:
    data_dir = tmp_path / "datasets"
    data_dir.mkdir()
    (data_dir / "gate_golden.jsonl").write_text("\n".join(gate_lines) + "\n")
    (data_dir / "spec_golden.jsonl").write_text(
        '{"id":"ok","spec":"## Problem\\nP\\n\\n## Proposed Approach\\nA\\n\\n## Acceptance Criteria\\n- C\\n","expected_ok":true}\n'
    )
    return data_dir


def test_run_evals_check_exits_nonzero_for_mis_gated_case(tmp_path) -> None:
    data_dir = write_eval_dataset(
        tmp_path,
        [
            '{"id":"unsafe-docs","changed_files":["docs/usage.md"],"diff":"+ok\\n","expected_decision":"escalate"}',
        ],
    )

    assert run_evals.main(["--check", "--data-dir", str(data_dir)]) == 1


def test_run_evals_check_exits_zero_for_clean_set(tmp_path) -> None:
    data_dir = write_eval_dataset(
        tmp_path,
        [
            '{"id":"safe-docs","changed_files":["docs/usage.md"],"diff":"+ok\\n","expected_decision":"merge"}',
            '{"id":"auth-change","changed_files":["internal/auth/login.go"],"diff":"+return x\\n","expected_decision":"escalate"}',
        ],
    )

    assert run_evals.main(["--check", "--data-dir", str(data_dir)]) == 0


def test_eval_threshold_boundary_exact_passes_just_below_fails() -> None:
    assert run_evals.gate_check_passes(GateMetrics(10, 0.9, 1.0, 1.0, ())) is True
    assert run_evals.gate_check_passes(GateMetrics(10, 0.899, 1.0, 1.0, ())) is False
    assert run_evals.gate_check_passes(GateMetrics(10, 1.0, 1.0, 0.999, ())) is False
