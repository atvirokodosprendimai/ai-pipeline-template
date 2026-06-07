from __future__ import annotations

from dataclasses import replace

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue
from wgmesh_pipeline.graph.build import build_graph
from wgmesh_pipeline.graph.nodes.gate import decide_gate, gate_node
from wgmesh_pipeline.graph.nodes.implement import implement_node
from wgmesh_pipeline.graph.nodes.review import review_node


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


def test_implement_derives_changed_files_from_existing_diff_for_gate() -> None:
    result = implement_node(
        {
            "issue": GitHubIssue(number=7, title="Fix keys", labels=("needs-triage",), state="open"),
            "diff": """diff --git a/internal/crypto/key.go b/internal/crypto/key.go
--- a/internal/crypto/key.go
+++ b/internal/crypto/key.go
+return key
""",
        }
    )

    decision = decide_gate(
        changed_files=result["changed_files"],
        diff=result["diff"],
        max_files=3,
        tests_passed=True,
        sanitise_ok=True,
        review_findings=[],
    )

    assert result["changed_files"] == ["internal/crypto/key.go"]
    assert decision.decision == "escalate"


def test_implement_created_pr_number_is_merged_by_gate() -> None:
    client = GitHubClient(cfg(mode="live"), session=SessionForPr({"number": 456}), sanitiser=lambda text: True)
    implemented = implement_node(
        {
            "issue": GitHubIssue(number=9, title="Fix relay", labels=("needs-triage",), state="open"),
            "github": client,
            "diff": """diff --git a/docs/readme.md b/docs/readme.md
--- a/docs/readme.md
+++ b/docs/readme.md
+docs
""",
        }
    )

    result = gate_node(
        {
            "issue": GitHubIssue(number=9, title="Fix relay", labels=("needs-triage",), state="open"),
            "github": client,
            "diff": implemented["diff"],
            "changed_files": implemented["changed_files"],
            "impl_pr": implemented["impl_pr"],
            "tests_passed": True,
            "sanitise_ok": True,
            "review_findings": [],
        },
        max_files=3,
    )

    assert implemented["impl_pr"] == 456
    assert result["decision"] == "merge"
    assert client.session.calls[-1]["url"].endswith("/pulls/456/merge")


def test_review_failed_verification_escalates_at_gate(monkeypatch) -> None:
    monkeypatch.setattr("wgmesh_pipeline.graph.nodes.review.run_sanitise", lambda text: True)

    reviewed = review_node(
        {
            "issue": GitHubIssue(number=8, title="Fix docs", labels=("needs-triage",), state="open"),
            "diff": "+docs\n",
            "changed_files": ["docs/readme.md"],
            "verification": {"tests_passed": False},
        }
    )
    decision = decide_gate(
        changed_files=reviewed["changed_files"],
        diff=reviewed["diff"],
        max_files=3,
        tests_passed=reviewed["tests_passed"],
        sanitise_ok=reviewed["sanitise_ok"],
        review_findings=reviewed["review_findings"],
    )

    assert reviewed["tests_passed"] is False
    assert decision.decision == "escalate"
    assert "tests failed" in decision.reasons


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
            "verification": {"tests_passed": True},
        }
    )

    assert result["visited"] == ["triage", "spec", "spec_pr", "implement", "review", "gate"]
    assert result["decision"] == "merge"
    assert result["diff"] == "+docs only\n"
    assert [record.operation for record in client.dry_run_records] == ["push_branch", "create_pr", "remove_label", "add_label", "merge_pr"]


class SessionForPr:
    def __init__(self, create_response: dict):
        self.create_response = create_response
        self.calls: list[dict] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        if method == "POST" and url.endswith("/pulls"):
            return ResponseForPr(self.create_response)
        return ResponseForPr({"merged": True})


class ResponseForPr:
    text = "json"

    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data
