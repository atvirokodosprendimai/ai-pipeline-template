from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from wgmesh_pipeline.config import Config, DEFAULT_TARGET_REPO, load_config
from wgmesh_pipeline.goose.runner import GooseRunner


REQUIRED_SECTIONS = ("## Classification", "## Problem Analysis", "## Proposed Approach")
SpecGenerator = Callable[[int], str]
SimilarityJudge = Callable[..., float]


@dataclass(frozen=True)
class IssueSpecReference:
    issue_number: int
    reference_path: Path


@dataclass(frozen=True)
class SpecParityReport:
    issue_number: int
    reference_path: str
    structural_pass: bool
    missing_sections: tuple[str, ...]
    similarity_score: float


def evaluate_spec_parity(
    references: Iterable[IssueSpecReference],
    *,
    spec_generator: SpecGenerator,
    judge: SimilarityJudge,
) -> list[SpecParityReport]:
    reports: list[SpecParityReport] = []
    for reference in references:
        reference_spec = reference.reference_path.read_text()
        box_spec = spec_generator(reference.issue_number)
        missing = missing_required_sections(box_spec)
        reports.append(
            SpecParityReport(
                issue_number=reference.issue_number,
                reference_path=str(reference.reference_path),
                structural_pass=not missing and not missing_required_sections(reference_spec),
                missing_sections=missing,
                similarity_score=float(judge(box_spec=box_spec, reference_spec=reference_spec)),
            )
        )
    return reports


def missing_required_sections(spec: str) -> tuple[str, ...]:
    return tuple(section for section in REQUIRED_SECTIONS if section not in spec)


def goose_spec_generator(config: Config, *, repo_path: str | Path) -> SpecGenerator:
    runner = GooseRunner(config)
    workdir = Path(repo_path)

    def generate(issue_number: int) -> str:
        spec_rel = Path("specs") / f"issue-{issue_number}-spec.md"
        result = runner.run_recipe(
            recipe="wgmesh-triage-spec.yaml",
            workdir=workdir,
            params={"issue_number": str(issue_number), "spec_file": str(spec_rel)},
            expected_output=spec_rel,
        )
        if not result.ok or result.output_path is None:
            raise RuntimeError(result.error or f"goose spec failed for issue {issue_number}")
        return result.output_path.read_text()

    return generate


def openevals_similarity_judge() -> SimilarityJudge:
    try:
        from openevals.llm import create_llm_as_judge
    except ImportError as exc:
        raise RuntimeError("openevals is required for the default similarity judge") from exc

    evaluator = create_llm_as_judge(
        prompt=(
            "Compare the generated technical spec to the reference spec. "
            "Return a numeric score from 0.0 to 1.0 for semantic similarity and implementation quality.\n\n"
            "Generated spec:\n{outputs}\n\nReference spec:\n{reference_outputs}"
        ),
        feedback_key="spec_parity",
    )

    def judge(*, box_spec: str, reference_spec: str) -> float:
        result = evaluator(outputs=box_spec, reference_outputs=reference_spec)
        return _score_from_result(result)

    return judge


def parse_references(values: Sequence[str]) -> list[IssueSpecReference]:
    references: list[IssueSpecReference] = []
    for value in values:
        issue, sep, path = value.partition("=")
        if not sep:
            raise ValueError(f"reference must be ISSUE=PATH, got {value!r}")
        references.append(IssueSpecReference(issue_number=int(issue), reference_path=Path(path)))
    return references


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only spec parity harness")
    parser.add_argument(
        "--reference",
        action="append",
        required=True,
        help="Issue/reference pair as ISSUE=PATH. May be repeated.",
    )
    parser.add_argument("--repo-path", default=".", help="Local wgmesh checkout used by Goose")
    args = parser.parse_args(argv)

    config = load_config({"TARGET_REPO": DEFAULT_TARGET_REPO, "PIPELINE_MODE": "shadow"})
    reports = evaluate_spec_parity(
        parse_references(args.reference),
        spec_generator=goose_spec_generator(config, repo_path=args.repo_path),
        judge=openevals_similarity_judge(),
    )
    for report in reports:
        print(json.dumps(asdict(report), sort_keys=True))
    return 0


def _score_from_result(result: object) -> float:
    if isinstance(result, (int, float)):
        return float(result)
    if isinstance(result, dict):
        for key in ("score", "value"):
            if key in result:
                return float(result[key])
        if "feedback" in result and isinstance(result["feedback"], dict):
            feedback = result["feedback"]
            for key in ("score", "value"):
                if key in feedback:
                    return float(feedback[key])
    score = getattr(result, "score", None)
    if score is not None:
        return float(score)
    raise RuntimeError(f"openevals result did not contain a numeric score: {result!r}")


if __name__ == "__main__":
    raise SystemExit(main())
