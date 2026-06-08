from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from evals.eval_gate import evaluate_gate, load_cases as load_gate_cases
from evals.eval_spec import evaluate_specs, load_cases as load_spec_cases
from evals.eval_trajectory import evaluate_trajectories


DATASETS = Path(__file__).resolve().parent / "datasets"
ESCALATE_RECALL_THRESHOLD = 1.0
AUTO_MERGE_PRECISION_THRESHOLD = 0.9


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when gate metrics fall below CI thresholds")
    parser.add_argument("--data-dir", type=Path, default=DATASETS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    gate = evaluate_gate(
        load_gate_cases(args.data_dir / "gate_golden.jsonl"),
        min_auto_merge_precision=0.0,
        min_escalate_recall=0.0,
        raise_on_failure=False,
    )
    specs = evaluate_specs(load_spec_cases(args.data_dir / "spec_golden.jsonl"))
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
    if args.check and not gate_check_passes(gate):
        print(
            "gate check failed: "
            f"auto_merge_precision threshold={AUTO_MERGE_PRECISION_THRESHOLD:.3f}, "
            f"escalate_recall threshold={ESCALATE_RECALL_THRESHOLD:.3f}, "
            f"failures={list(gate.failures)}",
            file=sys.stderr,
        )
        return 1
    if not args.check and gate.failures:
        return 1
    return 0


def gate_check_passes(gate) -> bool:
    return (
        gate.auto_merge_precision >= AUTO_MERGE_PRECISION_THRESHOLD
        and gate.escalate_recall >= ESCALATE_RECALL_THRESHOLD
        and not gate.failures
    )


if __name__ == "__main__":
    raise SystemExit(main())
