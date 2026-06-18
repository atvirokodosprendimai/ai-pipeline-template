from __future__ import annotations

import builtins
from dataclasses import dataclass, field

import pytest

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.graph import build_lg
from wgmesh_pipeline.graph.state import GraphState
from wgmesh_pipeline.tracing import build_callback_handler

pytestmark = pytest.mark.unit


def _cfg(**kwargs) -> Config:
    return Config(target_repo="atvirokodosprendimai/wgmesh", **kwargs)


@dataclass
class RecordingCompiled:
    result: GraphState | None = None
    configs: list[dict | None] = field(default_factory=list)

    def invoke(self, state: GraphState, config: dict | None = None) -> GraphState:
        self.configs.append(config)
        return self.result if self.result is not None else state


def _node(state: GraphState) -> GraphState:
    return state


def _gate(
    state: GraphState,
    *,
    max_files: int,
    apply_side_effects: bool = False,
) -> GraphState:
    return state


def _wrapper(config: Config, compiled: RecordingCompiled) -> build_lg.StateGraphWrapper:
    return build_lg.StateGraphWrapper(
        config=config,
        compiled=compiled,
        triage=_node,
        spec=_node,
        spec_pr=_node,
        implement=_node,
        review=_node,
        gate=_gate,
        raw_gate=_gate,
    )


def _state() -> GraphState:
    return {
        "issue": GitHubIssue(
            number=17,
            title="Trace StateGraph",
            labels=("fn:dev",),
            state="open",
        )
    }


def test_build_callback_handler_returns_none_without_langfuse_env() -> None:
    assert build_callback_handler(_cfg()) is None


def test_build_callback_handler_returns_none_when_import_fails(monkeypatch) -> None:
    real_import = builtins.__import__

    def failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "langfuse.langchain":
            raise ImportError("langfuse not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", failing_import)

    handler = build_callback_handler(
        _cfg(
            langfuse_host="https://langfuse.example",
            langfuse_public_key="pk",
            langfuse_secret_key="sk",
        )
    )

    assert handler is None


def test_state_graph_invoke_attaches_callbacks(monkeypatch) -> None:
    fake_handler = object()
    compiled = RecordingCompiled(result={"ok": True})
    wrapper = _wrapper(_cfg(), compiled)
    monkeypatch.setattr(
        build_lg,
        "build_callback_handler",
        lambda config: fake_handler,
    )

    result = wrapper.invoke(_state())

    assert result == {"ok": True}
    assert compiled.configs == [{"callbacks": [fake_handler]}]


def test_state_graph_invoke_uses_no_config_when_handler_absent(monkeypatch) -> None:
    compiled = RecordingCompiled()
    wrapper = _wrapper(_cfg(), compiled)
    state = _state()
    monkeypatch.setattr(build_lg, "build_callback_handler", lambda config: None)

    result = wrapper.invoke(state)

    assert result == state
    assert compiled.configs == [None]


def test_state_graph_invoke_ignores_handler_construction_failure(monkeypatch) -> None:
    compiled = RecordingCompiled()
    wrapper = _wrapper(_cfg(), compiled)
    state = _state()

    def boom(config):
        raise RuntimeError("callback init failed")

    monkeypatch.setattr(build_lg, "build_callback_handler", boom)

    result = wrapper.invoke(state)

    assert result == state
    assert compiled.configs == [None]
