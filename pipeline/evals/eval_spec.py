from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REQUIRED_SECTIONS = ("## Classification", "## Problem Analysis", "## Proposed Approach")


class SpecEvalFailure(AssertionError):
    pass


@dataclass(frozen=True)
class SpecMetrics:
    total: int
    passed: int
    failures: tuple[str, ...]


def load_cases(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def spec_is_structurally_ok(spec: str) -> bool:
    return all(section in spec for section in REQUIRED_SECTIONS)


def evaluate_specs(cases: Iterable[dict]) -> SpecMetrics:
    total = passed = 0
    failures: list[str] = []
    for case in cases:
        total += 1
        ok = spec_is_structurally_ok(case["spec"])
        if ok == case["expected_ok"]:
            passed += 1
        else:
            failures.append(f"{case['id']}: expected_ok={case['expected_ok']}, got {ok}")
    metrics = SpecMetrics(total=total, passed=passed, failures=tuple(failures))
    if failures:
        raise SpecEvalFailure(f"spec eval failed: {failures}")
    return metrics
