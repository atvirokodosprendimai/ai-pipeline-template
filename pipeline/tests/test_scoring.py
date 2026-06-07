from __future__ import annotations

from dataclasses import dataclass

import pytest

from wgmesh_pipeline.scoring import (
    NoopScorer,
    init_scoring,
    score_run,
)


@dataclass
class _Issue:
    number: int
    title: str = "t"


class _RecordingScorer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, *, issue, outcome, scores, tags) -> None:
        self.calls.append({"issue": issue, "outcome": outcome, "scores": scores, "tags": tags})


class _BoomScorer:
    def record(self, *, issue, outcome, scores, tags) -> None:
        raise RuntimeError("scoring backend down")


def _cfg(key: str | None):
    @dataclass(frozen=True)
    class C:
        langsmith_api_key: str | None
    return C(langsmith_api_key=key)


def test_init_scoring_noop_without_key() -> None:
    scorer = init_scoring(_cfg(None))
    assert isinstance(scorer, NoopScorer)


def test_init_scoring_uses_langsmith_with_key() -> None:
    scorer = init_scoring(_cfg("ls-key"))
    assert not isinstance(scorer, NoopScorer)
    # reset module scorer so other tests are unaffected
    init_scoring(_cfg(None))


def test_score_run_records_merged_outcome() -> None:
    rec = _RecordingScorer()
    state = {
        "issue": _Issue(584),
        "decision": "merge",
        "risk_tier": "low",
        "tests_passed": True,
        "sanitise_ok": True,
        "review_findings": [],
    }
    scores = score_run(state, outcome="merged", scorer=rec)
    assert scores["outcome"] == "merged"
    assert scores["auto_merged"] == 1
    assert scores["escalated"] == 0
    assert scores["risk_tier"] == "low"
    assert rec.calls[0]["issue"] == 584
    assert rec.calls[0]["tags"]["outcome"] == "merged"


def test_score_run_records_escalated_outcome() -> None:
    rec = _RecordingScorer()
    state = {
        "issue": _Issue(540),
        "decision": "escalate",
        "risk_tier": "high",
        "tests_passed": False,
        "review_findings": ["blocking"],
    }
    scores = score_run(state, outcome="escalated", scorer=rec)
    assert scores["escalated"] == 1
    assert scores["auto_merged"] == 0
    assert scores["review_findings_count"] == 1
    assert scores["risk_tier"] == "high"


def test_score_run_never_raises_when_backend_fails() -> None:
    # A failing scoring backend must never break the loop.
    scores = score_run({"issue": _Issue(1)}, outcome="failed", scorer=_BoomScorer())
    assert scores["outcome"] == "failed"


def test_score_run_handles_missing_issue() -> None:
    rec = _RecordingScorer()
    score_run({}, outcome="failed", scorer=rec)
    assert rec.calls[0]["issue"] == 0


def test_score_run_never_raises_on_malformed_state() -> None:
    # issue.number non-coercible and review_findings non-sized — both would
    # raise OUTSIDE a naive try. The whole body is guarded, so this returns
    # a minimal score instead of propagating into the loop.
    @dataclass
    class _BadIssue:
        number: str = "not-an-int"

    bad_state = {"issue": _BadIssue(), "review_findings": 123}
    scores = score_run(bad_state, outcome="merged", scorer=_RecordingScorer())
    assert scores["outcome"] == "merged"
