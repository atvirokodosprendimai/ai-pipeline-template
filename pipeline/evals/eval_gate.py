from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from wgmesh_pipeline.graph.nodes.gate import GateDecision, decide_gate


GateFunc = Callable[..., GateDecision]


class EvalFailure(AssertionError):
    pass


@dataclass(frozen=True)
class GateMetrics:
    total: int
    auto_merge_precision: float
    auto_merge_recall: float
    escalate_recall: float
    failures: tuple[str, ...]


def load_cases(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def evaluate_gate(
    cases: Iterable[dict],
    *,
    gate_func: GateFunc = decide_gate,
    max_files: int = 20,
    min_auto_merge_precision: float = 1.0,
    min_escalate_recall: float = 1.0,
) -> GateMetrics:
    failures: list[str] = []
    actual_auto = predicted_auto = true_auto = 0
    actual_escalate = true_escalate = 0
    total = 0

    for case in cases:
        total += 1
        expected = case["expected_decision"]
        decision = gate_func(
            changed_files=case["changed_files"],
            diff=case["diff"],
            max_files=max_files,
            tests_passed=case.get("tests_passed", True),
            sanitise_ok=case.get("sanitise_ok", True),
            review_findings=case.get("review_findings", []),
        ).decision
        if expected == "merge":
            actual_auto += 1
        if decision == "merge":
            predicted_auto += 1
        if expected == "merge" and decision == "merge":
            true_auto += 1
        if expected == "escalate":
            actual_escalate += 1
        if expected == "escalate" and decision == "escalate":
            true_escalate += 1
        if decision != expected:
            failures.append(f"{case['id']}: expected {expected}, got {decision}")

    precision = true_auto / predicted_auto if predicted_auto else 1.0
    auto_recall = true_auto / actual_auto if actual_auto else 1.0
    escalate_recall = true_escalate / actual_escalate if actual_escalate else 1.0
    metrics = GateMetrics(total, precision, auto_recall, escalate_recall, tuple(failures))
    if precision < min_auto_merge_precision or escalate_recall < min_escalate_recall or failures:
        raise EvalFailure(
            "gate eval failed: "
            f"auto_merge_precision={precision:.3f}, escalate_recall={escalate_recall:.3f}, failures={failures}"
        )
    return metrics


def broken_gate_always_merge(**kwargs) -> GateDecision:
    return GateDecision(decision="merge", risk_tier="low", reasons=())


def broken_gate_ignores_non_risk_guards(**kwargs) -> GateDecision:
    return decide_gate(
        changed_files=kwargs["changed_files"],
        diff=kwargs["diff"],
        max_files=kwargs["max_files"],
        tests_passed=True,
        sanitise_ok=True,
        review_findings=[],
    )
