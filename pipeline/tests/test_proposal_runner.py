"""U2 — decision proposal reroute through the configured per-surface executor.

The proposal runner must honor ``config.decision_executor`` via ``build_executor``
rather than constructing ``GooseRunner`` directly, so the decision surface flips
to langchain independently of the global ``EXECUTOR`` (and lands inert on goose).
"""

from __future__ import annotations

from typing import Any

import pytest

from wgmesh_pipeline.config import load_config
from wgmesh_pipeline.decision_lane import proposal_runner as pr

_BASE_ENV = {
    "TARGET_REPO": "atvirokodosprendimai/wgmesh",
    "DATABASE_MODE": "local",
    "WGMESH_BOT_PAT": "token",
    "ZAI_API_KEY": "zai",
}


class _FakeRunner:
    """Records the run_recipe call and writes the expected output file."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run_recipe(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        out = kwargs["workdir"] / kwargs["expected_output"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("PROPOSAL BODY", encoding="utf-8")

        class _Result:
            ok = True

        return _Result()


@pytest.mark.parametrize(
    "env, expected_name",
    [
        ({}, "goose"),  # default — lands inert on goose
        ({"EXECUTOR": "langchain"}, "langchain"),  # inherits the global
        (  # per-surface override wins over the global
            {"EXECUTOR": "langchain", "DECISION_EXECUTOR": "goose"},
            "goose",
        ),
    ],
)
def test_proposal_runner_selects_per_surface_executor(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    expected_name: str,
) -> None:
    cfg = load_config({**_BASE_ENV, **env, "WGMESH_CHECKOUT_PATH": str(tmp_path)})
    seen: dict[str, Any] = {}

    def _fake_build_executor(config: Any, *, executor_name: str | None = None) -> Any:
        seen["executor_name"] = executor_name
        return _FakeRunner()

    monkeypatch.setattr(pr, "build_executor", _fake_build_executor)
    (tmp_path / "STRATEGY.md").write_text("strategy", encoding="utf-8")

    proposal_fn = pr.build_proposal_fn(cfg)
    result = proposal_fn({"id": 7, "title": "Pricing page", "content": "brief"}, None)

    # The reroute resolved the backend from the per-surface decision_executor.
    assert seen["executor_name"] == expected_name
    assert cfg.decision_executor == expected_name
    # Free-form markdown proposal returned non-empty (no JSON contract).
    assert result == "PROPOSAL BODY"


def test_proposal_runner_raises_on_empty_output(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_config({**_BASE_ENV, "WGMESH_CHECKOUT_PATH": str(tmp_path)})

    class _NoOutputRunner:
        def run_recipe(self, **kwargs: Any) -> Any:
            class _Result:
                ok = False

            return _Result()

    monkeypatch.setattr(
        pr, "build_executor", lambda config, *, executor_name=None: _NoOutputRunner()
    )
    (tmp_path / "STRATEGY.md").write_text("strategy", encoding="utf-8")

    proposal_fn = pr.build_proposal_fn(cfg)
    with pytest.raises(RuntimeError, match="no output"):
        proposal_fn({"id": 8, "title": "x", "content": "b"}, None)
