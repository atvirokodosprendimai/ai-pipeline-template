from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class TrajectoryEvalFailure(AssertionError):
    pass


@dataclass(frozen=True)
class TrajectoryMetrics:
    total: int
    passed: int


def assert_never_skips_review(trace: Iterable[str]) -> None:
    nodes = list(trace)
    if "merge" in nodes and "review" not in nodes[: nodes.index("merge")]:
        raise TrajectoryEvalFailure("trajectory reached merge without review")


def evaluate_trajectories(traces: Iterable[Iterable[str]]) -> TrajectoryMetrics:
    total = passed = 0
    for trace in traces:
        total += 1
        assert_never_skips_review(trace)
        passed += 1
    return TrajectoryMetrics(total=total, passed=passed)

