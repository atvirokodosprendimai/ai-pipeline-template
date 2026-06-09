"""Online run scoring.

Every completed run records a structured score (gate decision, risk tier, the
green-signal inputs, and the terminal outcome) so live operation is observable
and feeds KPIs. Env-gated: a no-op scorer is used when LANGSMITH_API_KEY is
unset, mirroring tracing.py — scoring never crashes or blocks the loop.
"""

from __future__ import annotations

import sys
from typing import Any, Protocol

from wgmesh_pipeline.config import Config


class Scorer(Protocol):
    def record(
        self,
        *,
        issue: int,
        outcome: str,
        scores: dict[str, Any],
        tags: dict[str, str],
        trace_id: str | None = None,
    ) -> None:
        ...


class NoopScorer:
    def record(
        self,
        *,
        issue: int,
        outcome: str,
        scores: dict[str, Any],
        tags: dict[str, str],
        trace_id: str | None = None,
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
        self,
        *,
        issue: int,
        outcome: str,
        scores: dict[str, Any],
        tags: dict[str, str],
        trace_id: str | None = None,
    ) -> None:
        return None


class LangfuseScorer:
    """Online scores into self-hosted Langfuse. Defensive — never raises into
    the loop (score_run also guards, but keep the SDK calls safe here too)."""

    _warned = False

    def __init__(self, config: Config):
        from langfuse import Langfuse  # optional dep ([trace] extra)

        self._lf = Langfuse(
            public_key=config.langfuse_public_key,
            secret_key=config.langfuse_secret_key,
            host=config.langfuse_host,
        )

    def record(
        self,
        *,
        issue: int,
        outcome: str,
        scores: dict[str, Any],
        tags: dict[str, str],
        trace_id: str | None = None,
    ) -> None:
        try:
            # outcome as a categorical score + the numeric auto-merge signal,
            # tagged by issue. Visible in the Langfuse Scores view.
            # session_id groups every score (and trace) for one issue's pipeline
            # lifecycle into a single Langfuse session, AND is the required link:
            # create_score rejects a score with no trace_id/session_id/etc as a
            # 400 Bad request. issue-keyed session is the natural per-workflow id.
            session = f"issue-{issue}"
            common: dict[str, Any] = {
                "session_id": session,
                "metadata": {"issue": issue, **scores, **tags},
            }
            if trace_id:
                common["trace_id"] = trace_id
            # score_id is a stable idempotency key per (issue, score): the box
            # re-processes issues (retries, resets), so without it every pass
            # would append a DUPLICATE score. A stable id makes re-scoring an
            # update-in-place to the latest outcome.
            self._lf.create_score(
                name="pipeline_outcome",
                value=outcome,
                data_type="CATEGORICAL",
                score_id=f"{session}-pipeline_outcome",
                **common,
            )
            # Also emit the auto-merge signal as a BOOLEAN score so Langfuse can
            # aggregate it into a merge-rate-over-time KPI (a categorical score
            # only trends with a ScoreConfig; a boolean charts out of the box).
            auto_merged = scores.get("auto_merged")
            if auto_merged is not None:
                self._lf.create_score(
                    name="auto_merged",
                    value=float(auto_merged),
                    data_type="BOOLEAN",
                    score_id=f"{session}-auto_merged",
                    **common,
                )
            self._lf.flush()
            # Recovered: reset the latch so a *later* failure re-announces
            # instead of being masked by a single early transient blip.
            type(self)._warned = False
        except Exception as exc:
            self._announce(exc)

    @classmethod
    def _announce(cls, exc: BaseException) -> None:
        # Announce on the healthy->degraded transition (reset to False on a
        # successful score), not once-ever — a one-shot latch tripped by a
        # startup blip would silence a genuine sustained outage afterward.
        if not cls._warned:
            cls._warned = True
            print(f"[scoring] langfuse score failed, scoring degraded: {exc!r}", file=sys.stderr)


_scorer: Scorer = NoopScorer()


def init_scoring(config: Config, *, scorer: Scorer | None = None) -> Scorer:
    global _scorer
    if scorer is not None:
        _scorer = scorer
    elif config.langfuse_host and config.langfuse_public_key and config.langfuse_secret_key:
        try:
            _scorer = LangfuseScorer(config)
        except Exception:
            _scorer = NoopScorer()
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
    # The ENTIRE body is guarded — issue/score/tag construction included — so
    # malformed state can never raise into the poller loop. Scoring is
    # best-effort observability; on any failure we return a minimal score and
    # never propagate.
    scores: dict[str, Any] = {"outcome": outcome}
    try:
        sink = scorer if scorer is not None else _scorer
        issue = _issue_number(state)
        scores = _scores_from_state(state, outcome)
        tags = _tags_from_state(state, outcome)
        sink.record(issue=issue, outcome=outcome, scores=scores, tags=tags, trace_id=_trace_id_from_state(state))
    except Exception:
        pass
    return scores


def _scores_from_state(state: dict, outcome: str) -> dict[str, Any]:
    review = state.get("review_findings") or []
    attempts = int(state.get("escalation_attempts", 0))
    return {
        "outcome": outcome,
        "decision": state.get("decision"),
        "risk_tier": state.get("risk_tier"),
        "tests_passed": bool(state.get("tests_passed", False)),
        "sanitise_ok": bool(state.get("sanitise_ok", False)),
        "review_findings_count": len(review),
        "auto_merged": 1 if outcome == "merged" else 0,
        "escalated": 1 if outcome == "escalated" else 0,
        # Escalation-ladder attribution (R6): how far the climb went and whether
        # it recovered a build that tier 0 failed.
        "escalation_attempts": attempts,
        "escalation_tier": int(state.get("escalation_tier", 0)),
        "escalated_recovered": 1 if (attempts > 0 and outcome == "merged") else 0,
    }


def _issue_number(state: dict) -> int:
    issue = state.get("issue")
    number = getattr(issue, "number", None)
    return int(number) if number is not None else 0


def _tags_from_state(state: dict, outcome: str) -> dict[str, str]:
    tags = {
        "outcome": outcome,
        "decision": str(state.get("decision", "")),
        "risk_tier": str(state.get("risk_tier", "")),
    }
    for key in ("node", "stage", "error"):
        value = state.get(key)
        if value is not None:
            tags[key] = str(value)[:200]
    # Per-model attribution (R5): which model handled each LLM stage, so the
    # Scores dashboard can slice outcome/quality by model — the perf half of
    # price/performance routing.
    for key in ("spec_model_key", "implement_model_key"):
        value = state.get(key)
        if value is not None:
            tags[key] = str(value)[:200]
    # Escalation-ladder attribution (R6): group runs by terminal tier and whether
    # the climb recovered a tier-0 failure.
    if "escalation_attempts" in state:
        attempts = int(state.get("escalation_attempts", 0))
        tags["escalation_tier"] = str(state.get("escalation_tier", 0))
        tags["escalated_recovered"] = str(bool(attempts > 0 and outcome == "merged")).lower()
    return tags


def _trace_id_from_state(state: dict) -> str | None:
    for key in ("trace_id", "langfuse_trace_id"):
        value = state.get(key)
        if value:
            return str(value)
    trace = state.get("trace")
    if isinstance(trace, dict) and trace.get("id"):
        return str(trace["id"])
    return None
