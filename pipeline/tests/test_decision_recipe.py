"""Decision-proposal recipe (U5) — characterization of the prompt contract.

The recipe is consumed by Goose at runtime; these tests pin the section contract
+ the single-line-path-param guard (a multi-line param breaks the YAML scalar,
the same trap the observation recipe guards against)."""

from __future__ import annotations

from pathlib import Path

RECIPE = (
    Path(__file__).resolve().parents[1] / "recipes" / "wgmesh-decision-proposal.yaml"
)


def _text() -> str:
    return RECIPE.read_text(encoding="utf-8")


def test_recipe_declares_every_proposal_section() -> None:
    text = _text()
    for heading in (
        "## Recommendation",
        "## Options Considered",
        "## Pros",
        "## Cons",
        "## Upsides",
        "## Downsides",
        "## ROI / Cost",
        "## Assumptions",
    ):
        assert heading in text, f"recipe must require {heading!r}"


def test_recipe_requires_unverified_assumptions_framing() -> None:
    text = _text().lower()
    assert "no web research" in text
    assert "unverified" in text
    # never assert a market fact as settled
    assert "never assert" in text


def test_recipe_params_template_as_single_line_paths() -> None:
    # Goose substitutes {{ params }} into the YAML before parsing, so every param
    # must be a single-line path — a multi-line value breaks the prompt scalar.
    text = _text()
    for token in (
        "{{ brief_file }}",
        "{{ strategy_file }}",
        "{{ prior_proposal_file }}",
        "{{ feedback_file }}",
        "{{ proposal_file }}",
    ):
        assert token in text
    templated = text
    for token, val in (
        ("{{ brief_file }}", "/tmp/brief.md"),
        ("{{ strategy_file }}", "/tmp/STRATEGY.md"),
        ("{{ prior_proposal_file }}", "/tmp/prior.md"),
        ("{{ feedback_file }}", "/tmp/fb.md"),
        ("{{ proposal_file }}", "specs/proposal.md"),
        ("{{ decision_title }}", "Decide pricing"),
    ):
        templated = templated.replace(token, val)
    assert text.count("\n") == templated.count("\n")


def test_recipe_is_valid_yaml() -> None:
    import yaml

    doc = yaml.safe_load(_text())
    keys = {p["key"] for p in doc["parameters"]}
    assert {"decision_title", "brief_file", "proposal_file"} <= keys
