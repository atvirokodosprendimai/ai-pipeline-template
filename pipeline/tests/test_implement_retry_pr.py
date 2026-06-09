from __future__ import annotations

from pathlib import Path
from typing import Any

from wgmesh_pipeline.graph.nodes.implement import implement_node


class _Issue:
    def __init__(self, number: int) -> None:
        self.number = number
        self.title = "t"


class _RecordingClient:
    """Records create_pr / update_pr_body calls so the test can assert R5:
    a retry updates the existing PR, never creates a duplicate."""

    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []

    def create_pr(self, *, title, head, base, body) -> dict[str, Any]:
        self.create_calls.append({"title": title, "head": head, "base": base, "body": body})
        return {"number": 4242}

    def update_pr_body(self, pr_number: int, body: str) -> dict[str, Any]:
        self.update_calls.append({"pr_number": pr_number, "body": body})
        return {"number": pr_number}


class _FakeRunner:
    def __init__(self) -> None:
        self.tiers: list[int] = []

    def run_recipe(self, *, recipe, workdir, params, expected_output, stage=None, tier=0):
        self.tiers.append(tier)
        out = Path(workdir) / expected_output
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("diff --git a/x.go b/x.go\n+++ b/x.go\n+changed\n")

        class _R:
            ok = True
            output_path = out
            model_key = f"impl-tier-{tier}"
            error = None

        return _R()


def _base_state(client, runner, tmp_path, *, tier):
    return {
        "issue": _Issue(77),
        "github": client,
        "goose_runner": runner,
        "repo_path": tmp_path,
        "spec_path": "specs/issue-77-spec.md",
        "escalation_tier": tier,
    }


def test_first_pass_creates_one_pr_no_update(tmp_path) -> None:
    client = _RecordingClient()
    runner = _FakeRunner()
    out = implement_node(_base_state(client, runner, tmp_path, tier=0))
    assert len(client.create_calls) == 1
    assert client.update_calls == []
    assert out["impl_pr"] == 4242


def test_retry_updates_existing_pr_no_duplicate(tmp_path) -> None:
    client = _RecordingClient()
    runner = _FakeRunner()
    # simulate a retry: PR already exists, tier bumped to 1
    state = _base_state(client, runner, tmp_path, tier=1)
    state["impl_pr"] = 4242
    out = implement_node(state)
    # R5: no second PR created
    assert client.create_calls == []
    # PR body updated, noting the escalated tier + model
    assert len(client.update_calls) == 1
    assert client.update_calls[0]["pr_number"] == 4242
    assert "tier 1" in client.update_calls[0]["body"]
    assert "impl-tier-1" in client.update_calls[0]["body"]
    assert out["impl_pr"] == 4242


def test_retry_reruns_goose_even_with_stale_diff(tmp_path) -> None:
    client = _RecordingClient()
    runner = _FakeRunner()
    state = _base_state(client, runner, tmp_path, tier=2)
    state["impl_pr"] = 4242
    state["diff"] = "stale\n"  # must NOT short-circuit on a retry pass
    implement_node(state)
    assert runner.tiers == [2]  # Goose re-ran at tier 2
