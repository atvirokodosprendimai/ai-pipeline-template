from __future__ import annotations

from pathlib import Path

from evals.spec_parity import IssueSpecReference, evaluate_spec_parity


def test_spec_parity_flags_missing_proposed_approach(tmp_path: Path) -> None:
    reference = tmp_path / "reference.md"
    reference.write_text("## Classification\nfix\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it\n")

    reports = evaluate_spec_parity(
        [IssueSpecReference(issue_number=17, reference_path=reference)],
        spec_generator=lambda issue_number: "## Classification\nfix\n\n## Problem Analysis\nbug\n",
        judge=lambda *, box_spec, reference_spec: 0.25,
    )

    assert len(reports) == 1
    assert reports[0].issue_number == 17
    assert reports[0].structural_pass is False
    assert reports[0].missing_sections == ("## Proposed Approach",)


def test_spec_parity_similarity_scoring_uses_injected_judge(tmp_path: Path) -> None:
    reference = tmp_path / "reference.md"
    reference.write_text("## Classification\nfix\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it\n")
    judge_calls: list[tuple[str, str]] = []

    def judge(*, box_spec: str, reference_spec: str) -> float:
        judge_calls.append((box_spec, reference_spec))
        return 0.88

    reports = evaluate_spec_parity(
        [IssueSpecReference(issue_number=17, reference_path=reference)],
        spec_generator=lambda issue_number: "## Classification\nfix\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it differently\n",
        judge=judge,
    )

    assert reports[0].structural_pass is True
    assert reports[0].similarity_score == 0.88
    assert judge_calls == [
        (
            "## Classification\nfix\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it differently\n",
            "## Classification\nfix\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it\n",
        )
    ]
