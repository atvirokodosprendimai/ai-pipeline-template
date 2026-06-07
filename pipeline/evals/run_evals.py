from __future__ import annotations

import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from evals.eval_gate import evaluate_gate, load_cases as load_gate_cases
from evals.eval_spec import evaluate_specs, load_cases as load_spec_cases
from evals.eval_trajectory import evaluate_trajectories


DATASETS = Path(__file__).resolve().parent / "datasets"


def main() -> int:
    gate = evaluate_gate(load_gate_cases(DATASETS / "gate_golden.jsonl"))
    specs = evaluate_specs(load_spec_cases(DATASETS / "spec_golden.jsonl"))
    trajectory = evaluate_trajectories(
        [
            ["triage", "spec", "implement", "review", "gate", "merge"],
            ["triage", "spec", "implement", "review", "gate", "escalate"],
        ]
    )

    print(
        "gate: "
        f"total={gate.total} auto_merge_precision={gate.auto_merge_precision:.3f} "
        f"auto_merge_recall={gate.auto_merge_recall:.3f} escalate_recall={gate.escalate_recall:.3f}"
    )
    print(f"spec: total={specs.total} passed={specs.passed}")
    print(f"trajectory: total={trajectory.total} passed={trajectory.passed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

