from __future__ import annotations

from dataclasses import dataclass
import sys
from types import SimpleNamespace

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.scoring import (
    LangfuseScorer,
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

    def record(self, *, issue, outcome, scores, tags, trace_id=None) -> None:
        self.calls.append({"issue": issue, "outcome": outcome, "scores": scores, "tags": tags, "trace_id": trace_id})


class _BoomScorer:
    def record(self, *, issue, outcome, scores, tags, trace_id=None) -> None:
        raise RuntimeError("scoring backend down")


class _FakeLangfuse:
    def __init__(self) -> None:
        self.scores: list[dict] = []
        self.flushed = False

    def create_score(self, **kwargs) -> None:
        self.scores.append(kwargs)

    def flush(self) -> None:
        self.flushed = True


class _BoomLangfuse(_FakeLangfuse):
    def create_score(self, **kwargs) -> None:
        raise RuntimeError("langfuse down")


def _cfg(key: str | None):
    @dataclass(frozen=True)
    class C:
        langsmith_api_key: str | None
        langfuse_host: str | None = None
        langfuse_public_key: str | None = None
        langfuse_secret_key: str | None = None
    return C(langsmith_api_key=key)


def _langfuse_cfg() -> Config:
    return Config(
        target_repo="atvirokodosprendimai/wgmesh",
        langfuse_host="https://langfuse.example",
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
    )


def _install_fake_langfuse(monkeypatch, client):
    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(Langfuse=lambda **kwargs: client))
    return LangfuseScorer(_langfuse_cfg())


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


def test_langfuse_record_creates_pipeline_outcome_score_and_flushes(monkeypatch) -> None:
    client = _FakeLangfuse()
    scorer = _install_fake_langfuse(monkeypatch, client)

    scorer.record(
        issue=584,
        outcome="merged",
        scores={"auto_merged": 1, "risk_tier": "low"},
        tags={"node": "reviewed", "outcome": "merged"},
    )

    assert client.scores == [
        {
            "name": "pipeline_outcome",
            "value": "merged",
            "data_type": "CATEGORICAL",
            "metadata": {
                "issue": 584,
                "auto_merged": 1,
                "risk_tier": "low",
                "node": "reviewed",
                "outcome": "merged",
            },
        }
    ]
    assert client.flushed is True


def test_score_run_passes_trace_id_to_langfuse_when_present(monkeypatch) -> None:
    client = _FakeLangfuse()
    scorer = _install_fake_langfuse(monkeypatch, client)

    score_run({"issue": _Issue(12), "trace_id": "trace-abc"}, outcome="failed", scorer=scorer)

    assert client.scores[0]["trace_id"] == "trace-abc"


def test_score_run_omits_trace_id_when_absent(monkeypatch) -> None:
    client = _FakeLangfuse()
    scorer = _install_fake_langfuse(monkeypatch, client)

    score_run({"issue": _Issue(13)}, outcome="failed", scorer=scorer)

    assert "trace_id" not in client.scores[0]


def test_langfuse_record_warns_once_when_score_upload_fails(monkeypatch, capsys) -> None:
    client = _BoomLangfuse()
    scorer = _install_fake_langfuse(monkeypatch, client)
    LangfuseScorer._warned = False

    first = score_run({"issue": _Issue(1)}, outcome="failed", scorer=scorer)
    second = score_run({"issue": _Issue(1)}, outcome="failed", scorer=scorer)

    assert first["outcome"] == "failed"
    assert second["outcome"] == "failed"
    err = capsys.readouterr().err
    assert err.count("scoring degraded") == 1


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


def test_score_run_records_failed_outcome() -> None:
    rec = _RecordingScorer()
    scores = score_run({"issue": _Issue(541)}, outcome="failed", scorer=rec)

    assert scores["outcome"] == "failed"
    assert scores["auto_merged"] == 0
    assert scores["escalated"] == 0
    assert rec.calls[0]["outcome"] == "failed"


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


def test_langfuse_record_reannounces_after_recovery(monkeypatch, capsys) -> None:
    """Announce on healthy->degraded transition, not once-ever: a success
    resets the latch so a later failure re-announces (sustained outage stays
    visible after an early transient blip)."""
    LangfuseScorer._warned = False

    class _Toggle(_FakeLangfuse):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def create_score(self, **kwargs) -> None:
            if self.fail:
                raise RuntimeError("langfuse down")
            super().create_score(**kwargs)

    client = _Toggle()
    scorer = _install_fake_langfuse(monkeypatch, client)
    scorer.record(issue=1, outcome="failed", scores={}, tags={})   # fail -> announce #1
    client.fail = False
    scorer.record(issue=1, outcome="merged", scores={}, tags={})   # success -> reset latch
    client.fail = True
    scorer.record(issue=1, outcome="failed", scores={}, tags={})   # fail -> announce #2
    err = capsys.readouterr().err
    assert err.count("scoring degraded") == 2
    LangfuseScorer._warned = False
