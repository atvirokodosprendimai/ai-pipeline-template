from __future__ import annotations

import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeVar

from wgmesh_pipeline.config import Config


T = TypeVar("T")


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


_tracer: Tracer = NoopTracer()


def init_tracing(config: Config, *, tracer: Tracer | None = None) -> Tracer:
    global _tracer
    if tracer is not None:
        _tracer = tracer
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

