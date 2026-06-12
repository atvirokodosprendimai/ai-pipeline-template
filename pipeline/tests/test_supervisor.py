"""Supervisor-Rank parity + edge-case tests (cutover U5).

The parity fixture reconstructs a snapshot that classifies/ranks to exactly
the values recorded in ``company/supervisor-rank-state.json`` on main, then
asserts the Python ranker reproduces the recorded ordering, stage summary,
top actions, AND the byte-exact sha256 material fingerprint the Actions
ranker (jq -Sc + sha256sum) committed. A matching fingerprint proves the
material payload — top ids, stage summary, unknown count, top actions — is
byte-identical to what the workflow produced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wgmesh_pipeline.forge.protocol import ForgeIssue
from wgmesh_pipeline.supervisor import (
    RankResult,
    SupervisorInputs,
    build_state,
    classify_stage,
    load_taxonomy,
    material_fingerprint,
    rank_clogs,
    run_supervisor_rank,
    snapshot_from_forge,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
# FROZEN fixture — a copy of company/supervisor-rank-state.json at the time
# the parity values were recorded. The live file mutates every 4h cron run;
# parity must pin the recorded inputs, not chase a moving file (broke CI on
# the first post-merge cron commit, 2026-06-12).
STATE_FILE = Path(__file__).parent / "fixtures" / "supervisor_rank_state.json"
TAXONOMY_FILE = REPO_ROOT / "company" / "pipeline-stages.json"

AIT = "atvirokodosprendimai/ai-pipeline-template"
WG = "atvirokodosprendimai/wgmesh"
NOW = "2026-06-12T00:00:00Z"


@pytest.fixture(scope="module")
def taxonomy() -> dict:
    return load_taxonomy(TAXONOMY_FILE)


@pytest.fixture(scope="module")
def recorded_state() -> dict:
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _item(repo: str, type_: str, number: int, title: str, created: str, labels=()) -> dict:
    return {
        "repo": repo,
        "type": type_,
        "number": number,
        "title": title,
        "labels": [{"name": name} for name in labels],
        "created_at": created,
        "updated_at": created,
        "is_draft": False,
        "url": f"https://github.com/{repo}/{'pull' if type_ == 'pr' else 'issues'}/{number}",
    }


def parity_snapshot() -> list[dict]:
    """Snapshot reproducing the recorded state on main (run #24).

    1 triage + 4 spec + 5 review + 1 unknown = the recorded stage_summary;
    dwell ordering reproduces the recorded top-5 and top-3.
    """
    return [
        # triage: bare issue, no labels (issue_without_type_label rule)
        _item(AIT, "issue", 934, "supervisor-rank: top pipeline clogs", "2026-05-01T00:00:00Z"),
        # review: needs-human override
        _item(WG, "issue", 652, "wgmesh release blocked", "2026-05-20T00:00:00Z", ["needs-human"]),
        # spec x4: title-prefix override
        _item(WG, "pr", 667, "spec: Issue #650", "2026-06-01T00:00:00Z"),
        _item(WG, "pr", 689, "spec: Issue #670", "2026-06-05T00:00:00Z"),
        _item(WG, "pr", 691, "spec: Issue #672", "2026-06-07T00:00:00Z"),
        _item(WG, "pr", 700, "spec: Issue #680", "2026-06-11T12:00:00Z"),
        # review x4 (below top-5 dwell)
        _item(WG, "pr", 701, "fix: mesh route flap", "2026-06-11T18:00:00Z", ["needs-review"]),
        _item(WG, "pr", 702, "fix: peer key rotation", "2026-06-11T18:00:00Z", ["needs-review"]),
        _item(WG, "pr", 703, "feat: metrics endpoint", "2026-06-11T18:00:00Z", ["needs-review"]),
        _item(WG, "pr", 704, "docs: peering guide", "2026-06-11T18:00:00Z", ["needs-review"]),
        # unknown: labelled issue matching no rule
        _item(AIT, "issue", 900, "ATP autobuyer ledger drift", "2026-06-10T00:00:00Z", ["question"]),
    ]


def parity_result(taxonomy: dict) -> RankResult:
    return rank_clogs(
        SupervisorInputs(items=tuple(parity_snapshot()), taxonomy=taxonomy, now=NOW)
    )


class TestParityWithRecordedState:
    """The ranker reproduces the Actions ranker's recorded run on main."""

    def test_top3_ids_match_recorded(self, taxonomy, recorded_state):
        result = parity_result(taxonomy)
        assert result.top_ids == recorded_state["last_run_top_ids"]

    def test_top_actions_match_recorded(self, taxonomy, recorded_state):
        result = parity_result(taxonomy)
        assert result.top_actions == recorded_state["top_actions"]

    def test_stage_summary_matches_recorded(self, taxonomy, recorded_state):
        result = parity_result(taxonomy)
        assert dict(result.stage_summary) == recorded_state["stage_summary"]

    def test_unknown_count_matches_recorded(self, taxonomy, recorded_state):
        result = parity_result(taxonomy)
        assert len(result.unknown) == recorded_state["unknown_count"]

    def test_material_fingerprint_byte_exact(self, taxonomy, recorded_state):
        """sha256(jq -Sc payload) committed by Actions == Python fingerprint."""
        result = parity_result(taxonomy)
        assert material_fingerprint(result) == recorded_state["material_fingerprint"]

    def test_state_dict_matches_recorded_shape_and_gates(self, taxonomy, recorded_state):
        run = build_state(parity_result(taxonomy), recorded_state)
        assert list(run.state.keys()) == list(recorded_state.keys())
        # Same material → fingerprint gate closed, no rank change, run +1.
        assert run.material_changed is False
        assert run.rank_changed is False
        assert run.state["run_number"] == recorded_state["run_number"] + 1
        assert run.state["issue_number"] == recorded_state["issue_number"]
        assert run.state["issue_url"] == recorded_state["issue_url"]
        assert run.state["material_fingerprint"] == recorded_state["material_fingerprint"]

    def test_rank_order_and_scores(self, taxonomy):
        result = parity_result(taxonomy)
        assert [c.rank for c in result.top] == [1, 2, 3, 4, 5]
        assert [c.number for c in result.top] == [934, 652, 667, 689, 691]
        # score = dwell_hours x downstream_blocked_count (all multipliers 1 here)
        assert [c.score for c in result.top] == [1008, 552, 264, 168, 120]
        assert all(c.score == c.dwell_hours * c.downstream_blocked_count for c in result.top)


class TestClassification:
    def test_needs_human_overrides_everything(self, taxonomy):
        item = _item(WG, "pr", 1, "spec: also a spec title", NOW, ["needs-human"])
        assert classify_stage(item, taxonomy) == "review"

    def test_spec_title_prefix_case_insensitive(self, taxonomy):
        assert classify_stage(_item(WG, "issue", 2, "Spec: thing", NOW), taxonomy) == "spec"

    def test_approved_clean_pr_is_merge(self, taxonomy):
        item = {**_item(WG, "pr", 3, "feat: ready", NOW),
                "review_decision": "APPROVED", "merge_state_status": "CLEAN"}
        assert classify_stage(item, taxonomy) == "merge"

    def test_approved_dirty_pr_is_not_merge(self, taxonomy):
        item = {**_item(WG, "pr", 4, "feat: conflicted", NOW),
                "review_decision": "APPROVED", "merge_state_status": "DIRTY"}
        assert classify_stage(item, taxonomy) != "merge"

    def test_labelled_issue_matching_nothing_is_unknown(self, taxonomy):
        item = _item(WG, "issue", 5, "mystery", NOW, ["question"])
        assert classify_stage(item, taxonomy) == "unknown"

    def test_bare_issue_is_triage(self, taxonomy):
        assert classify_stage(_item(WG, "issue", 6, "mystery", NOW), taxonomy) == "triage"

    def test_copilot_triaging_dwell_starts_at_updated_at(self, taxonomy):
        item = {**_item(WG, "issue", 7, "stuck", "2026-06-01T00:00:00Z", ["copilot-triaging"]),
                "updated_at": "2026-06-11T00:00:00Z"}
        result = rank_clogs(SupervisorInputs(items=(item,), taxonomy=taxonomy, now=NOW))
        assert result.top[0].stage == "triage"
        assert result.top[0].dwell_hours == 24  # from updated_at, not created_at


class TestRankingMechanics:
    def test_empty_inputs(self, taxonomy):
        result = rank_clogs(SupervisorInputs(items=(), taxonomy=taxonomy, now=NOW))
        assert result.top == ()
        assert result.unknown == ()
        assert dict(result.stage_summary) == {
            "triage": 0, "spec": 0, "build": 0, "review": 0,
            "merge": 0, "verify": 0, "revenue": 0, "unknown": 0,
        }
        run = build_state(result, None)
        assert run.material_changed is True  # no prior fingerprint → gate open
        assert run.rank_changed is False  # empty prior top never flags
        assert run.state["run_number"] == 1
        assert run.state["last_run_top_ids"] == []

    def test_ties_break_by_created_at_then_repo_then_number(self, taxonomy):
        items = (
            _item(WG, "pr", 20, "fix: b", "2026-06-11T00:00:00Z", ["needs-review"]),
            _item(WG, "pr", 10, "fix: a", "2026-06-11T00:00:00Z", ["needs-review"]),
            _item(AIT, "pr", 30, "fix: c", "2026-06-11T00:00:00Z", ["needs-review"]),
            _item(WG, "pr", 40, "fix: older", "2026-06-10T00:00:00Z", ["needs-review"]),
        )
        # 40 wins on score (higher dwell); the 24h tie sorts created, repo, number.
        result = rank_clogs(SupervisorInputs(items=items, taxonomy=taxonomy, now=NOW))
        assert [c.number for c in result.top] == [40, 30, 10, 20]

    def test_all_healthy_zero_dwell_scores_zero(self, taxonomy):
        items = (
            _item(WG, "pr", 50, "spec: fresh", NOW),
            _item(WG, "pr", 51, "fix: fresh", NOW, ["needs-review"]),
        )
        result = rank_clogs(SupervisorInputs(items=items, taxonomy=taxonomy, now=NOW))
        assert [c.score for c in result.top] == [0, 0]
        assert [c.number for c in result.top] == [50, 51]  # repo+number tiebreak

    def test_spec_blocked_count_multiplies_by_builds_in_repo(self, taxonomy):
        items = (
            _item(WG, "pr", 60, "spec: clogged", "2026-06-11T00:00:00Z"),
            _item(WG, "pr", 61, "impl: one", NOW, ["approved-for-build"]),
            _item(WG, "pr", 62, "impl: two", NOW, ["goose-implementation"]),
        )
        result = rank_clogs(SupervisorInputs(items=items, taxonomy=taxonomy, now=NOW))
        spec = next(c for c in result.top if c.number == 60)
        assert spec.downstream_blocked_count == 2
        assert spec.score == 24 * 2

    def test_unknown_excluded_from_top_listed_sorted(self, taxonomy):
        items = (
            _item(WG, "issue", 71, "mystery b", NOW, ["question"]),
            _item(AIT, "issue", 70, "mystery a", NOW, ["question"]),
        )
        result = rank_clogs(SupervisorInputs(items=items, taxonomy=taxonomy, now=NOW))
        assert result.top == ()
        assert [u["id"] for u in result.unknown] == [f"{AIT}#70", f"{WG}#71"]

    def test_top_n_truncates(self, taxonomy):
        items = tuple(
            _item(WG, "pr", 80 + i, f"fix: {i}", "2026-06-11T00:00:00Z", ["needs-review"])
            for i in range(7)
        )
        result = rank_clogs(SupervisorInputs(items=items, taxonomy=taxonomy, now=NOW, top_n=5))
        assert len(result.top) == 5

    def test_rank_changed_when_top3_differs(self, taxonomy):
        result = parity_result(taxonomy)
        prev = {"last_run_top_ids": ["x#1", "y#2", "z#3"], "run_number": 3,
                "material_fingerprint": "stale"}
        run = build_state(result, prev)
        assert run.rank_changed is True
        assert run.material_changed is True
        assert run.state["run_number"] == 4

    def test_fingerprint_gate_idempotent_across_runs(self, taxonomy):
        first = build_state(parity_result(taxonomy), None)
        assert first.material_changed is True
        second = build_state(parity_result(taxonomy), first.state)
        assert second.material_changed is False
        assert second.state["material_fingerprint"] == first.state["material_fingerprint"]


class _ReadOnlyForge:
    """Fake exposing ONLY the read method the runner may use; any write blows up."""

    def __init__(self, issues: list[ForgeIssue]) -> None:
        self._issues = issues
        self.write_calls: list[str] = []

    def list_open_issues(self) -> list[ForgeIssue]:
        return self._issues

    def __getattr__(self, name: str):
        raise AssertionError(f"runner must not call forge.{name} in parity phase")


class TestRunner:
    def test_runner_returns_state_without_forge_writes(self, taxonomy):
        forge = _ReadOnlyForge([
            ForgeIssue(number=1, title="bare issue", labels=(), state="open"),
            ForgeIssue(number=2, title="spec: thing", labels=(), state="open",
                       pull_request={"url": "x"}),
        ])
        run = run_supervisor_rank(forge, taxonomy=taxonomy, repo=WG, now=NOW)
        assert run.state["last_run_at"] == NOW
        assert run.state["run_number"] == 1
        assert run.state["stage_summary"]["triage"] == 1
        assert run.state["stage_summary"]["spec"] == 1
        # No timestamps via the Forge protocol → degraded dwell (gap documented)
        assert all(c.dwell_hours == 0 for c in run.result.top)
        assert forge.write_calls == []

    def test_runner_prefers_explicit_snapshot(self, taxonomy, recorded_state):
        forge = _ReadOnlyForge([])
        run = run_supervisor_rank(
            forge,
            taxonomy=taxonomy,
            repo=WG,
            previous_state=recorded_state,
            snapshot=parity_snapshot(),
            now=NOW,
        )
        assert run.state["material_fingerprint"] == recorded_state["material_fingerprint"]
        assert run.material_changed is False

    def test_snapshot_from_forge_marks_prs(self, taxonomy):
        forge = _ReadOnlyForge([
            ForgeIssue(number=3, title="t", labels=("bug",), state="open",
                       pull_request={"url": "x"}),
        ])
        snapshot = snapshot_from_forge(forge, WG)
        assert snapshot[0]["type"] == "pr"
        assert snapshot[0]["repo"] == WG
        assert snapshot[0]["labels"] == ["bug"]
