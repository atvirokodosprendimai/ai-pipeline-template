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
    _BOOLEAN,
    _classify_verify,
    _GEN_FILTER,
    _JUDGE_MODEL,
    _NUMERIC,
    _post_registration_enriched_gen,
    _PIKAPODS_SNAPSHOT,
    _redo_rule_registered_at,
    _SHIPPED_SNAPSHOT,
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
def test_redo_of_shipped_capability_evaluator_shape_and_prompt() -> None:
    matches = [
        ev for ev in EVALUATORS if ev["name"] == "redo_of_shipped_capability"
    ]

    assert len(matches) == 1
    evaluator = matches[0]
    assert evaluator["type"] == "llm_as_judge"
    assert evaluator["variables"] == ["output"]
    assert evaluator["outputDefinition"] is _NUMERIC
    assert evaluator["modelConfig"] is _JUDGE_MODEL
    assert "{{output}}" in evaluator["prompt"]
    assert "REDO" in evaluator["prompt"]
    assert "OpenPanel" in evaluator["prompt"]
    assert "not applicable" in evaluator["prompt"].lower()
    assert "downstream consumer" in evaluator["prompt"].lower()
    assert "OpenPanel" in _SHIPPED_SNAPSHOT
    assert "Buttondown" in _SHIPPED_SNAPSHOT


@pytest.mark.unit
def test_redo_of_shipped_capability_rule_shape() -> None:
    matches = [
        rule for rule in RULES if rule["name"] == "rule_redo_of_shipped_capability"
    ]

    assert len(matches) == 1
    rule = matches[0]
    assert rule["evaluatorName"] == "redo_of_shipped_capability"
    assert rule["target"] == "observation"
    assert rule["filter"] is _GEN_FILTER
    assert rule["mapping"] == [{"variable": "output", "source": "output"}]


@pytest.mark.unit
def test_gen_filter_excludes_judge_self_calls() -> None:
    # type=GENERATION plus a name-exclusion of the eval worker's own ChatAnthropic
    # judge calls (recursive-scoring fix).
    type_cond = [c for c in _GEN_FILTER if c["column"] == "type"]
    name_cond = [c for c in _GEN_FILTER if c["column"] == "name"]

    assert type_cond and type_cond[0]["value"] == ["GENERATION"]
    assert name_cond, "filter must exclude judge self-calls by name"
    assert name_cond[0]["operator"] == "none of"
    assert "ChatAnthropic" in name_cond[0]["value"]


@pytest.mark.unit
def test_rules_reference_existing_evaluators() -> None:
    evaluator_names = {ev["name"] for ev in EVALUATORS}

    assert all(rule["evaluatorName"] in evaluator_names for rule in RULES)


@pytest.mark.unit
@pytest.mark.unit
def test_no_component_paywall_evaluator_shape_and_prompt() -> None:
    matches = [ev for ev in EVALUATORS if ev["name"] == "no_component_paywall"]

    assert len(matches) == 1
    evaluator = matches[0]
    assert evaluator["type"] == "llm_as_judge"
    assert evaluator["variables"] == ["output"]
    assert evaluator["outputDefinition"] is _BOOLEAN
    assert evaluator["modelConfig"] is _JUDGE_MODEL
    assert "{{output}}" in evaluator["prompt"]
    assert (
        "payment, license key, account state, trial/time limit, or remote "
        "authorization" in evaluator["prompt"]
    )
    assert "managed service" in evaluator["prompt"].lower()


@pytest.mark.unit
def test_no_component_paywall_rule_shape() -> None:
    matches = [rule for rule in RULES if rule["name"] == "rule_no_component_paywall"]

    assert len(matches) == 1
    rule = matches[0]
    assert rule["evaluatorName"] == "no_component_paywall"
    assert rule["target"] == "observation"
    assert rule["sampling"] == 1.0
    assert rule["filter"] is _GEN_FILTER
    assert rule["mapping"] == [{"variable": "output", "source": "output"}]


def test_setup_langfuse_evaluator_counts() -> None:
    assert len(EVALUATORS) == 6
    assert len(RULES) == 6


@pytest.mark.unit
def test_dry_run_prints_open_source_default(capsys) -> None:
    assert main(["--dry-run"]) == 0

    captured = capsys.readouterr()
    assert "open_source_default" in captured.out
    assert "rule_open_source_default" in captured.out
    assert "redo_of_shipped_capability" in captured.out
    assert "rule_redo_of_shipped_capability" in captured.out


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


def _verify_request(gens: list, scores: list, rules: list | None = None):
    def fake_request(method: str, path: str, body=None) -> tuple[int, object]:
        if "observations" in path:
            return 200, {"data": gens}
        if "scores" in path:
            return 200, {"data": scores}
        if "evaluation-rules" in path:
            return 200, {"data": rules or []}
        return 200, {"data": []}

    return fake_request


@pytest.mark.unit
def test_classify_verify_no_generations_fails() -> None:
    verdict, message = _classify_verify(
        gens_count=0,
        box_gens=[],
        enriched=[],
        redo_scores=0,
        other_eval_scores=0,
        post_registration_enriched_gen=False,
    )

    assert verdict == "FAIL"
    assert (
        message
        == "VERIFY: NO GENERATION observations in Langfuse — the box is not emitting "
        "generation traces, so the evaluator has nothing to score (wired but off the "
        "execution path). Instrument the box's LLM calls before this eval can fire."
    )
    assert mod._verify_exit_code(verdict) == 1


@pytest.mark.unit
def test_classify_verify_redo_score_passes() -> None:
    verdict, message = _classify_verify(
        gens_count=1,
        box_gens=[],
        enriched=[],
        redo_scores=2,
        other_eval_scores=0,
        post_registration_enriched_gen=True,
    )

    assert verdict == "PASS"
    assert (
        message
        == "VERIFY: PASS — 2 redo_of_shipped_capability score(s) on real "
        "generations. Evaluator is firing end-to-end."
    )
    assert mod._verify_exit_code(verdict) == 0


@pytest.mark.unit
def test_classify_verify_waits_without_post_registration_generation() -> None:
    verdict, message = _classify_verify(
        gens_count=1,
        box_gens=[{"name": "triage-llm"}],
        enriched=[],
        redo_scores=0,
        other_eval_scores=3,
        post_registration_enriched_gen=False,
    )

    assert verdict == "WAIT"
    assert (
        message
        == "VERIFY: WAIT — the score pipeline is ALIVE (3 score(s) "
        "from sibling evaluators), but no redo score yet. This is a non-failing "
        "awaiting-the-first-post-registration-generation state; re-run verify after "
        "the next box generation."
    )
    assert mod._verify_exit_code(verdict) == 0


@pytest.mark.unit
def test_classify_verify_fails_when_redo_filter_appears_broken() -> None:
    verdict, message = _classify_verify(
        gens_count=1,
        box_gens=[{"name": "triage-llm"}],
        enriched=[{"name": "triage-llm", "output": "ship this"}],
        redo_scores=0,
        other_eval_scores=3,
        post_registration_enriched_gen=True,
    )

    assert verdict == "FAIL"
    assert (
        message
        == "VERIFY: FAIL — the score pipeline is ALIVE (3 score(s) from sibling "
        "evaluators), and a post-registration enriched box generation exists, but "
        "redo_of_shipped_capability still has zero scores. The redo rule's "
        "GENERATION filter appears broken; inspect the rule filter/mapping before "
        "trusting this evaluator."
    )
    assert mod._verify_exit_code(verdict) == 1


@pytest.mark.unit
def test_classify_verify_no_scores_fails() -> None:
    verdict, message = _classify_verify(
        gens_count=1,
        box_gens=[{"name": "triage-llm"}],
        enriched=[],
        redo_scores=0,
        other_eval_scores=0,
        post_registration_enriched_gen=False,
    )

    assert verdict == "FAIL"
    assert (
        message
        == "VERIFY: FAIL — box generations exist but NO evaluator (redo or sibling) has any "
        "score. The eval-rule -> score path is not firing at all; fix that before trusting "
        "any judge. Check the Langfuse default eval-model connection and rule enablement."
    )
    assert mod._verify_exit_code(verdict) == 1


@pytest.mark.unit
def test_classify_verify_is_pure(monkeypatch) -> None:
    def fail_request(*_args, **_kwargs):
        raise AssertionError("classifier must not perform network I/O")

    monkeypatch.setattr(mod, "_request", fail_request)
    args = {
        "gens_count": 1,
        "box_gens": [{"name": "triage-llm"}],
        "enriched": [],
        "redo_scores": 0,
        "other_eval_scores": 3,
        "post_registration_enriched_gen": False,
    }

    assert _classify_verify(**args) == _classify_verify(**args)


@pytest.mark.unit
def test_redo_rule_registered_at_reads_created_at(monkeypatch) -> None:
    def fake_request(method: str, path: str, body=None) -> tuple[int, object]:
        assert method == "GET"
        assert path == f"{mod._UNSTABLE}/evaluation-rules"
        return (
            200,
            {
                "data": [
                    {
                        "name": "rule_redo_of_shipped_capability",
                        "id": "rule-id",
                        "createdAt": "2026-06-20T01:00:00Z",
                    }
                ]
            },
        )

    monkeypatch.setattr(mod, "_request", fake_request)

    assert _redo_rule_registered_at() == "2026-06-20T01:00:00Z"


@pytest.mark.unit
@pytest.mark.parametrize("timestamp_key", ["createdAt", "created_at", "timestamp"])
def test_redo_rule_registered_at_accepts_common_timestamp_keys(
    monkeypatch, timestamp_key: str
) -> None:
    def fake_request(method: str, path: str, body=None) -> tuple[int, object]:
        return (
            200,
            {
                "evaluationRules": [
                    {
                        "name": "rule_redo_of_shipped_capability",
                        "id": "rule-id",
                        timestamp_key: "2026-06-20T01:00:00Z",
                    }
                ]
            },
        )

    monkeypatch.setattr(mod, "_request", fake_request)

    assert _redo_rule_registered_at() == "2026-06-20T01:00:00Z"


@pytest.mark.unit
def test_redo_rule_registered_at_returns_none_without_timestamp(monkeypatch) -> None:
    def fake_request(method: str, path: str, body=None) -> tuple[int, object]:
        return (
            200,
            {
                "data": [
                    {
                        "name": "rule_redo_of_shipped_capability",
                        "id": "rule-id",
                    }
                ]
            },
        )

    monkeypatch.setattr(mod, "_request", fake_request)

    assert _redo_rule_registered_at() is None


@pytest.mark.unit
def test_post_registration_enriched_gen_after_registration() -> None:
    enriched = [{"name": "triage-llm", "startTime": "2026-06-20T01:00:01Z"}]

    assert (
        _post_registration_enriched_gen(enriched, "2026-06-20T01:00:00Z")
        is enriched[0]
    )


@pytest.mark.unit
def test_post_registration_enriched_gen_before_registration() -> None:
    enriched = [{"name": "triage-llm", "startTime": "2026-06-20T00:59:59Z"}]

    assert _post_registration_enriched_gen(enriched, "2026-06-20T01:00:00Z") is None


@pytest.mark.unit
def test_post_registration_enriched_gen_timestamp_absent_fallback() -> None:
    enriched = [{"name": "triage-llm", "startTime": "2026-06-20T00:59:59Z"}]

    assert _post_registration_enriched_gen(enriched, None) is enriched[0]


@pytest.mark.unit
def test_post_registration_enriched_gen_no_enriched_generations() -> None:
    assert _post_registration_enriched_gen([], None) is None
    assert _post_registration_enriched_gen([], "2026-06-20T01:00:00Z") is None


@pytest.mark.unit
def test_verify_pass_when_redo_scores_present(monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "_request",
        _verify_request(
            gens=[{"startTime": "t", "name": "gate", "traceId": "x"}],
            # live Langfuse names scores after the rule, not the evaluator
            scores=[{"name": "rule_redo_of_shipped_capability", "value": 1.0}],
        ),
    )
    assert mod.verify() == 0


@pytest.mark.unit
def test_verify_fails_when_no_generations(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_request", _verify_request(gens=[], scores=[]))
    assert mod.verify() == 1


@pytest.mark.unit
def test_verify_fails_when_no_eval_scores_at_all(monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "_request",
        _verify_request(gens=[{"startTime": "t", "name": "gate"}], scores=[]),
    )
    assert mod.verify() == 1


@pytest.mark.unit
def test_verify_waits_when_siblings_score_but_redo_absent(monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "_request",
        _verify_request(
            gens=[{"startTime": "t", "name": "gate"}],
            scores=[{"name": "rule_growth_issue_quality", "value": 0.8}],
        ),
    )
    # pipeline alive but no scoreable redo generation yet — WAIT is non-failing
    assert mod.verify() == 0


@pytest.mark.unit
def test_verify_fails_when_siblings_score_but_redo_filter_appears_broken(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        mod,
        "_request",
        _verify_request(
            gens=[
                {
                    "startTime": "2026-06-20T10:01:00Z",
                    "name": "triage-llm",
                    "traceId": "x",
                    "output": "real issue text",
                }
            ],
            scores=[{"name": "rule_growth_issue_quality", "value": 0.8}],
            rules=[
                {
                    "name": "rule_redo_of_shipped_capability",
                    "createdAt": "2026-06-20T10:00:00Z",
                }
            ],
        ),
    )

    assert mod.verify() == 1


@pytest.mark.unit
def test_verify_waits_when_enriched_generation_predates_rule(monkeypatch) -> None:
    def fake_request(method: str, path: str, body=None) -> tuple[int, object]:
        if "observations" in path:
            return 200, {
                "data": [
                    {
                        "startTime": "2026-06-20T09:59:00Z",
                        "name": "triage-llm",
                        "traceId": "x",
                        "output": "real issue text",
                    }
                ]
            }
        if "scores" in path:
            return 200, {"data": [{"name": "rule_growth_issue_quality", "value": 0.8}]}
        if "evaluation-rules" in path:
            return 200, {
                "data": [
                    {
                        "id": "rule-id",
                        "name": "rule_redo_of_shipped_capability",
                        "createdAt": "2026-06-20T10:00:00Z",
                    }
                ]
            }
        return 200, {"data": []}

    monkeypatch.setattr(mod, "_request", fake_request)

    assert mod.verify() == 0
