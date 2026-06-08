from __future__ import annotations

import sys
import time
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeVar

from wgmesh_pipeline.config import Config


T = TypeVar("T")


def _session_ctx(issue: str | None):
    """Group all of an issue's stage spans under one Langfuse session.
    propagate_attributes(session_id=...) tags every span created within the
    context; one session per issue = that issue's full pipeline lifecycle.
    Guarded: a missing/changed SDK symbol must never break tracing."""
    if not issue:
        return nullcontext()
    try:
        from langfuse import propagate_attributes  # public v4 API

        return propagate_attributes(session_id=f"issue-{issue}")
    except Exception:
        return nullcontext()


class Span(Protocol):
    def end(self, *, outputs: Any = None, error: BaseException | None = None, latency_seconds: float = 0.0) -> None:
        ...


class Tracer(Protocol):
    def start_span(self, *, name: str, inputs: Any, tags: dict[str, str]) -> Span:
        ...


@dataclass
class NoopSpan:
    def end(self, *, outputs: Any = None, error: BaseException | None = None, latency_seconds: float = 0.0) -> None:
        return None


class NoopTracer:
    def start_span(self, *, name: str, inputs: Any, tags: dict[str, str]) -> Span:
        return NoopSpan()


class LangSmithTracer:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def start_span(self, *, name: str, inputs: Any, tags: dict[str, str]) -> Span:
        # Phase 1 keeps the LangSmith dependency optional. The local span object
        # preserves the instrumentation boundary; real upload can be swapped in
        # without touching node code once the deployment secret exists.
        return NoopSpan()


class _LangfuseSpan:
    """Defensive wrapper — tracing must NEVER raise into the loop, so every
    Langfuse SDK call is guarded. Falls back to a silent no-op on any error."""

    # Only the first swallowed SDK error is announced, so a version/API break
    # (e.g. langfuse v3 `start_span` → v4 `start_observation`) surfaces instead
    # of silently degrading to a no-op tracer for the life of the process.
    _warned = False

    def __init__(self, lf: Any, name: str, inputs: Any, tags: dict[str, str]):
        self._lf = lf
        self._span = None
        try:
            # langfuse v4 dropped the client-level `start_span`; the equivalent
            # is `start_observation(..., as_type="span")`. Fall back to the v3
            # name so a downgraded SDK keeps working. Create the span inside the
            # issue's session context so all its stage spans group together.
            with _session_ctx(tags.get("issue")):
                if hasattr(lf, "start_observation"):
                    self._span = lf.start_observation(name=name, as_type="span", input=inputs, metadata=tags)
                else:
                    self._span = lf.start_span(name=name, input=inputs, metadata=tags)
        except Exception as exc:  # never raise into the loop
            self._span = None
            self._announce(exc)

    @classmethod
    def _announce(cls, exc: BaseException) -> None:
        if not cls._warned:
            cls._warned = True
            print(f"[tracing] langfuse span creation failed, tracing degraded: {exc!r}", file=sys.stderr)

    def end(self, *, outputs: Any = None, error: BaseException | None = None, latency_seconds: float = 0.0) -> None:
        try:
            if self._span is not None:
                if error is not None:
                    self._span.update(level="ERROR", status_message=str(error))
                else:
                    self._span.update(output=outputs)
                self._span.end()
            self._lf.flush()
        except Exception as exc:
            self._announce(exc)


class LangfuseTracer:
    def __init__(self, config: Config):
        from langfuse import Langfuse  # optional dep ([trace] extra)

        self._lf = Langfuse(
            public_key=config.langfuse_public_key,
            secret_key=config.langfuse_secret_key,
            host=config.langfuse_host,
        )

    def start_span(self, *, name: str, inputs: Any, tags: dict[str, str]) -> Span:
        return _LangfuseSpan(self._lf, name, inputs, tags)


_tracer: Tracer = NoopTracer()


def init_tracing(config: Config, *, tracer: Tracer | None = None) -> Tracer:
    global _tracer
    if tracer is not None:
        _tracer = tracer
    elif config.langfuse_host and config.langfuse_public_key and config.langfuse_secret_key:
        try:
            _tracer = LangfuseTracer(config)
        except Exception:
            _tracer = NoopTracer()
    elif config.langsmith_api_key:
        _tracer = LangSmithTracer(config.langsmith_api_key)
    else:
        _tracer = NoopTracer()
    return _tracer


def trace_node(name: str, fn: Callable[[T], T]) -> Callable[[T], T]:
    def wrapped(state: T) -> T:
        tags = _tags_for_state(state, name)
        span = _tracer.start_span(name=name, inputs=_safe_state(state), tags=tags)
        started = time.monotonic()
        try:
            result = fn(state)
        except BaseException as exc:
            span.end(error=exc, latency_seconds=time.monotonic() - started)
            raise
        span.end(outputs=_safe_state(result), latency_seconds=time.monotonic() - started)
        return result

    wrapped.__name__ = getattr(fn, "__name__", name)
    return wrapped


def _tags_for_state(state: Any, stage: str) -> dict[str, str]:
    tags = {"stage": stage}
    if isinstance(state, dict) and "issue" in state:
        issue = state["issue"]
        number = getattr(issue, "number", None)
        if number is not None:
            tags["issue"] = str(number)
    return tags


def _safe_state(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    safe = dict(value)
    safe.pop("github", None)
    safe.pop("goose_runner", None)
    return safe

