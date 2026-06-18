from __future__ import annotations

import sys
from pathlib import Path

import pytest

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from evals.setup_langfuse_evaluators import (  # noqa: E402
    EVALUATORS,
    RULES,
    _GEN_FILTER,
    _JUDGE_MODEL,
    _NUMERIC,
    _PIKAPODS_SNAPSHOT,
    main,
)


@pytest.mark.unit
def test_open_source_default_evaluator_shape_and_prompt() -> None:
    matches = [ev for ev in EVALUATORS if ev["name"] == "open_source_default"]

    assert len(matches) == 1
    evaluator = matches[0]
    assert evaluator["type"] == "llm_as_judge"
    assert evaluator["variables"] == ["output"]
    assert evaluator["outputDefinition"] is _NUMERIC
    assert evaluator["modelConfig"] is _JUDGE_MODEL
    assert "{{output}}" in evaluator["prompt"]
    assert "Intercom" in evaluator["prompt"]
    assert "Answer" in evaluator["prompt"]
    assert "Zapier" in evaluator["prompt"]
    assert "Activepieces" in evaluator["prompt"]
    assert "not applicable" in evaluator["prompt"].lower()
    assert "PikaPods self-hosts these open-source apps" in _PIKAPODS_SNAPSHOT


@pytest.mark.unit
def test_open_source_default_rule_shape() -> None:
    matches = [rule for rule in RULES if rule["name"] == "rule_open_source_default"]

    assert len(matches) == 1
    rule = matches[0]
    assert rule["evaluatorName"] == "open_source_default"
    assert rule["target"] == "observation"
    assert rule["filter"] is _GEN_FILTER
    assert rule["mapping"] == [{"variable": "output", "source": "output"}]


@pytest.mark.unit
def test_rules_reference_existing_evaluators() -> None:
    evaluator_names = {ev["name"] for ev in EVALUATORS}

    assert all(rule["evaluatorName"] in evaluator_names for rule in RULES)


@pytest.mark.unit
def test_setup_langfuse_evaluator_counts() -> None:
    assert len(EVALUATORS) == 4
    assert len(RULES) == 4


@pytest.mark.unit
def test_dry_run_prints_open_source_default(capsys) -> None:
    assert main(["--dry-run"]) == 0

    captured = capsys.readouterr()
    assert "open_source_default" in captured.out
    assert "rule_open_source_default" in captured.out
