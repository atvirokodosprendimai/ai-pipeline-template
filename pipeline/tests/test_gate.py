from __future__ import annotations

from dataclasses import replace

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue
from wgmesh_pipeline.graph.build import build_graph
from wgmesh_pipeline.graph.nodes.gate import decide_gate


def cfg(mode: str = "shadow") -> Config:
    return Config(target_repo="atvirokodosprendimai/wgmesh", mode=mode, max_files=3)


def test_gate_merges_low_risk_green_clean_review() -> None:
    decision = decide_gate(
        changed_files=["docs/readme.md"],
        diff="+docs\n",
        max_files=3,
        tests_passed=True,
        sanitise_ok=True,
        review_findings=[],
    )

    assert decision.decision == "merge"
    assert decision.risk_tier == "low"


def test_gate_escalates_high_risk_path_even_when_green() -> None:
    decision = decide_gate(
        changed_files=["internal/auth/login.go"],
        diff="+return nil\n",
        max_files=3,
        tests_passed=True,
        sanitise_ok=True,
        review_findings=[],
    )

    assert decision.decision == "escalate"
    assert decision.risk_tier == "high"


def test_gate_escalates_blocking_review_finding() -> None:
    decision = decide_gate(
        changed_files=["docs/readme.md"],
        diff="+docs\n",
        max_files=3,
        tests_passed=True,
        sanitise_ok=True,
        review_findings=[{"blocking": True, "message": "missing test"}],
    )

    assert decision.decision == "escalate"
    assert "blocking review finding" in decision.reasons


def test_gate_escalates_sanitise_failure() -> None:
    decision = decide_gate(
        changed_files=["docs/readme.md"],
        diff="+docs\n",
        max_files=3,
        tests_passed=True,
        sanitise_ok=False,
        review_findings=[],
    )

    assert decision.decision == "escalate"
    assert "sanitise failed" in decision.reasons


def test_graph_wont_do_routes_to_escalate_and_skips_spec_implement() -> None:
    client = GitHubClient(cfg())
    graph = build_graph(cfg())

    result = graph.invoke(
        {
            "issue": GitHubIssue(number=5, title="wont fix old path", labels=("needs-triage",), state="open"),
            "github": client,
        }
    )

    assert result["decision"] == "escalate"
    assert result["visited"] == ["triage", "escalate"]
    assert [record.operation for record in client.dry_run_records] == ["add_label"]


def test_graph_full_fix_path_reaches_gate_with_diff_and_shadow_has_no_network_writes(monkeypatch) -> None:
    client = GitHubClient(cfg())
    graph = build_graph(cfg())
    monkeypatch.setattr("wgmesh_pipeline.graph.nodes.review.run_sanitise", lambda text: True)

    result = graph.invoke(
        {
            "issue": GitHubIssue(number=6, title="Fix docs", labels=("needs-triage",), state="open"),
            "github": client,
            "diff": "+docs only\n",
            "changed_files": ["docs/readme.md"],
            "impl_pr": 123,
        }
    )

    assert result["visited"] == ["triage", "spec", "implement", "review", "gate"]
    assert result["decision"] == "merge"
    assert result["diff"] == "+docs only\n"
    assert [record.operation for record in client.dry_run_records] == ["merge_pr"]

