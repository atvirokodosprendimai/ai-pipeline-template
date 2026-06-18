from __future__ import annotations

import sys
from pathlib import Path

import pytest

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from evals import setup_langfuse_evaluators as mod  # noqa: E402
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


@pytest.mark.unit
def test_apply_patches_existing_rules(monkeypatch) -> None:
    existing_rule_ids = {
        rule["name"]: f"rule-id-{idx}" for idx, rule in enumerate(RULES)
    }
    calls = []

    monkeypatch.setattr(mod, "_existing_rule_ids", lambda: existing_rule_ids)

    def fake_request(method: str, path: str, body=None) -> tuple[int, object]:
        calls.append((method, path))
        if path == f"{mod._UNSTABLE}/evaluators":
            return 200, {"scope": "project"}
        return 200, {}

    monkeypatch.setattr(mod, "_request", fake_request)

    assert mod.apply(dry_run=False) == 0
    rule_calls = calls[len(EVALUATORS) :]

    assert len(rule_calls) == len(RULES)
    assert all(method == "PATCH" for method, _path in rule_calls)
    assert all("/evaluation-rules/rule-id-" in path for _method, path in rule_calls)
    assert not any(
        method == "POST" and path == f"{mod._UNSTABLE}/evaluation-rules"
        for method, path in rule_calls
    )


@pytest.mark.unit
def test_apply_posts_fresh_rules(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(mod, "_existing_rule_ids", lambda: {})

    def fake_request(method: str, path: str, body=None) -> tuple[int, object]:
        calls.append((method, path))
        if path == f"{mod._UNSTABLE}/evaluators":
            return 200, {"scope": "project"}
        return 200, {}

    monkeypatch.setattr(mod, "_request", fake_request)

    assert mod.apply(dry_run=False) == 0
    rule_calls = calls[len(EVALUATORS) :]

    assert rule_calls == [
        ("POST", f"{mod._UNSTABLE}/evaluation-rules") for _rule in RULES
    ]


@pytest.mark.unit
def test_apply_treats_rule_name_conflict_as_success(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_existing_rule_ids", lambda: {})

    def fake_request(method: str, path: str, body=None) -> tuple[int, object]:
        if path == f"{mod._UNSTABLE}/evaluators":
            return 200, {"scope": "project"}
        return 409, '{"code":"name_conflict","message":"already exists"}'

    monkeypatch.setattr(mod, "_request", fake_request)

    assert mod.apply(dry_run=False) == 0


@pytest.mark.unit
def test_apply_keeps_genuine_rule_failure(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_existing_rule_ids", lambda: {})

    def fake_request(method: str, path: str, body=None) -> tuple[int, object]:
        if path == f"{mod._UNSTABLE}/evaluators":
            return 200, {"scope": "project"}
        return 500, "boom"

    monkeypatch.setattr(mod, "_request", fake_request)

    assert mod.apply(dry_run=False) > 0
