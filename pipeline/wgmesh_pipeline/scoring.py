"""Online run scoring.

Every completed run records a structured score (gate decision, risk tier, the
green-signal inputs, and the terminal outcome) so live operation is observable
and feeds KPIs. Env-gated: a no-op scorer is used when LANGSMITH_API_KEY is
unset, mirroring tracing.py — scoring never crashes or blocks the loop.
"""

from __future__ import annotations

from typing import Any, Protocol

from wgmesh_pipeline.config import Config


class Scorer(Protocol):
    def record(
        self, *, issue: int, outcome: str, scores: dict[str, Any], tags: dict[str, str]
    ) -> None:
        ...


class NoopScorer:
    def record(
        self, *, issue: int, outcome: str, scores: dict[str, Any], tags: dict[str, str]
    ) -> None:
        return None


class LangSmithScorer:
    """Instrumentation boundary for LangSmith online feedback.

    Keeps the call shape stable; the real ``create_feedback`` upload is swapped
    in once the deployment secret exists, without touching caller code.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key

    def record(
        self, *, issue: int, outcome: str, scores: dict[str, Any], tags: dict[str, str]
    ) -> None:
        return None


_scorer: Scorer = NoopScorer()


def init_scoring(config: Config, *, scorer: Scorer | None = None) -> Scorer:
    global _scorer
    if scorer is not None:
        _scorer = scorer
    elif config.langsmith_api_key:
        _scorer = LangSmithScorer(config.langsmith_api_key)
    else:
        _scorer = NoopScorer()
    return _scorer


def score_run(state: dict, *, outcome: str, scorer: Scorer | None = None) -> dict[str, Any]:
    """Record a terminal-outcome score for a run.

    outcome is one of: merged | escalated | failed. Returns the scores dict that
    was recorded (also useful for assertions/tests). Never raises — scoring must
    not break the loop.
    """
    sink = scorer if scorer is not None else _scorer
    issue = _issue_number(state)
    scores = _scores_from_state(state, outcome)
    tags = {"outcome": outcome, "decision": str(state.get("decision", "")), "risk_tier": str(state.get("risk_tier", ""))}
    try:
        sink.record(issue=issue, outcome=outcome, scores=scores, tags=tags)
    except Exception:
        # Scoring is best-effort observability; never propagate into the loop.
        pass
    return scores


def _scores_from_state(state: dict, outcome: str) -> dict[str, Any]:
    review = state.get("review_findings") or []
    return {
        "outcome": outcome,
        "decision": state.get("decision"),
        "risk_tier": state.get("risk_tier"),
        "tests_passed": bool(state.get("tests_passed", False)),
        "sanitise_ok": bool(state.get("sanitise_ok", False)),
        "review_findings_count": len(review),
        "auto_merged": 1 if outcome == "merged" else 0,
        "escalated": 1 if outcome == "escalated" else 0,
    }


def _issue_number(state: dict) -> int:
    issue = state.get("issue")
    number = getattr(issue, "number", None)
    return int(number) if number is not None else 0
