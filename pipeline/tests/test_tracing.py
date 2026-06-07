from __future__ import annotations

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.tracing import init_tracing, trace_node


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

