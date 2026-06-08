from __future__ import annotations

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.tracing import _LangfuseSpan, init_tracing, trace_node


class _FakeSdkSpan:
    def __init__(self, record):
        self.record = record
        self.ended = False

    def update(self, **kwargs):
        self.record.setdefault("updates", []).append(kwargs)

    def end(self):
        self.ended = True
        self.record["ended"] = True


class _FakeLangfuseV4:
    """Mirrors langfuse>=4: client exposes start_observation, NOT start_span."""

    def __init__(self):
        self.record = {}
        self.flushed = False

    def start_observation(self, *, name, as_type, input, metadata):
        self.record.update({"name": name, "as_type": as_type, "input": input, "metadata": metadata})
        return _FakeSdkSpan(self.record)

    def flush(self):
        self.flushed = True


class _FakeLangfuseV3:
    """Mirrors langfuse 3.x: client exposes start_span only."""

    def __init__(self):
        self.record = {}
        self.flushed = False

    def start_span(self, *, name, input, metadata):
        self.record.update({"name": name, "input": input, "metadata": metadata})
        return _FakeSdkSpan(self.record)

    def flush(self):
        self.flushed = True


def test_langfuse_span_uses_v4_start_observation() -> None:
    lf = _FakeLangfuseV4()
    span = _LangfuseSpan(lf, "triage", {"x": 1}, {"stage": "triage"})
    span.end(outputs={"classification": "fix"})

    assert lf.record["name"] == "triage"
    assert lf.record["as_type"] == "span"  # proves v4 path taken, not silent no-op
    assert lf.record["ended"] is True
    assert lf.flushed is True
    assert {"output": {"classification": "fix"}} in lf.record["updates"]


def test_langfuse_span_falls_back_to_v3_start_span() -> None:
    lf = _FakeLangfuseV3()
    span = _LangfuseSpan(lf, "triage", {"x": 1}, {"stage": "triage"})
    span.end(outputs={"ok": True})

    assert lf.record["name"] == "triage"
    assert lf.record["ended"] is True
    assert lf.flushed is True


def test_langfuse_span_swallows_sdk_break_but_warns(capsys) -> None:
    _LangfuseSpan._warned = False

    class _Broken:
        def start_observation(self, **kwargs):
            raise AttributeError("api drift")

    span = _LangfuseSpan(_Broken(), "triage", {}, {})  # must NOT raise into loop
    span.end(outputs={})
    err = capsys.readouterr().err
    assert "tracing degraded" in err


class FakeSpan:
    def __init__(self, record):
        self.record = record

    def end(self, *, outputs=None, error=None, latency_seconds=0.0):
        self.record["outputs"] = outputs
        self.record["error"] = error
        self.record["latency_seconds"] = latency_seconds


class FakeTracer:
    def __init__(self):
        self.records = []

    def start_span(self, *, name, inputs, tags):
        record = {"name": name, "inputs": inputs, "tags": tags}
        self.records.append(record)
        return FakeSpan(record)


def test_key_set_with_mocked_tracer_emits_span_with_tags() -> None:
    tracer = FakeTracer()
    init_tracing(Config(target_repo="atvirokodosprendimai/wgmesh", langsmith_api_key="key"), tracer=tracer)

    def node(state):
        return {**state, "classification": "fix"}

    wrapped = trace_node("triage", node)
    result = wrapped({"issue": GitHubIssue(number=12, title="Fix", labels=(), state="open")})

    assert result["classification"] == "fix"
    assert tracer.records[0]["name"] == "triage"
    assert tracer.records[0]["tags"] == {"stage": "triage", "issue": "12"}
    assert tracer.records[0]["outputs"]["classification"] == "fix"


def test_key_unset_noop_still_runs_node_normally() -> None:
    init_tracing(Config(target_repo="atvirokodosprendimai/wgmesh"))

    def node(state):
        return {**state, "classification": "feature"}

    result = trace_node("triage", node)({"issue": GitHubIssue(number=13, title="Feature", labels=(), state="open")})

    assert result["classification"] == "feature"



def test_langfuse_span_groups_into_issue_session(monkeypatch) -> None:
    """All of an issue's stage spans are created inside
    propagate_attributes(session_id=issue-<N>) so they group into one Langfuse
    session (the issue's pipeline lifecycle)."""
    import contextlib
    import langfuse as lf_mod

    calls = {}

    @contextlib.contextmanager
    def fake_propagate(*, session_id=None, **kw):
        calls["session_id"] = session_id
        yield

    monkeypatch.setattr(lf_mod, "propagate_attributes", fake_propagate, raising=False)

    _LangfuseSpan(_FakeLangfuseV4(), "triage", {"x": 1}, {"stage": "triage", "issue": "584"})
    assert calls.get("session_id") == "issue-584"


def test_langfuse_span_no_issue_uses_no_session(monkeypatch) -> None:
    import contextlib
    import langfuse as lf_mod

    calls = {"used": False}

    @contextlib.contextmanager
    def fake_propagate(*, session_id=None, **kw):
        calls["used"] = True
        yield

    monkeypatch.setattr(lf_mod, "propagate_attributes", fake_propagate, raising=False)
    lf = _FakeLangfuseV4()
    _LangfuseSpan(lf, "triage", {}, {"stage": "triage"})  # no issue tag
    assert calls["used"] is False
    assert lf.record["name"] == "triage"  # span still created
