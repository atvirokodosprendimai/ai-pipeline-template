from __future__ import annotations

from pathlib import Path

from evals import spec_parity
from evals.spec_parity import IssueSpecReference, evaluate_spec_parity


RECIPE = Path(__file__).resolve().parents[1] / "recipes" / "wgmesh-triage-spec.yaml"


def test_spec_parity_flags_missing_proposed_approach(tmp_path: Path) -> None:
    reference = tmp_path / "reference.md"
    reference.write_text("## Classification\nbug\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it\n")

    reports = evaluate_spec_parity(
        [IssueSpecReference(issue_number=17, reference_path=reference)],
        spec_generator=lambda issue_number: "## Classification\nbug\n\n## Problem Analysis\nbug\n",
        judge=lambda *, box_spec, reference_spec: 0.25,
    )

    assert len(reports) == 1
    assert reports[0].issue_number == 17
    assert reports[0].structural_pass is False
    assert reports[0].missing_sections == ("## Proposed Approach",)


def test_spec_parity_similarity_scoring_uses_injected_judge(tmp_path: Path) -> None:
    reference = tmp_path / "reference.md"
    reference.write_text("## Classification\nbug\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it\n")
    judge_calls: list[tuple[str, str]] = []

    def judge(*, box_spec: str, reference_spec: str) -> float:
        judge_calls.append((box_spec, reference_spec))
        return 0.88

    reports = evaluate_spec_parity(
        [IssueSpecReference(issue_number=17, reference_path=reference)],
        spec_generator=lambda issue_number: "## Classification\nbug\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it differently\n",
        judge=judge,
    )

    assert reports[0].structural_pass is True
    assert reports[0].similarity_score == 0.88
    assert judge_calls == [
        (
            "## Classification\nbug\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it differently\n",
            "## Classification\nbug\n\n## Problem Analysis\nbug\n\n## Proposed Approach\nfix it\n",
        )
    ]


def test_recipe_prompt_demands_validator_sections() -> None:
    # Raw-text check on purpose: CI installs only the package deps, which do
    # not include a YAML parser. The validator headings appear solely in the
    # recipe's prompt block, so substring assertions carry the same guarantee.
    recipe_text = RECIPE.read_text()

    for section in spec_parity.REQUIRED_SECTIONS:
        assert section in recipe_text

    for stale_heading in ("## Summary", "## Context", "## Requirements"):
        assert stale_heading not in recipe_text
