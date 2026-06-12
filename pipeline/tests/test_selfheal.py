"""Self-Heal parity + runner tests (cutover U4).

The parity fixture replays the run recorded in
``company/pipeline-health-state.json`` on main (a healthy nothing-to-heal
check) and asserts the Python runner reproduces the WHOLE state file
byte-exact — counters, retry tracker, funnel/idle signals, summary, and the
mutation assertion, in the workflow's jq key order. Detector-level edges
live in ``test_selfheal_detectors.py``.
"""

from __future__ import annotations

import json

import pytest

from selfheal_fixtures import (
    NOW,
    STATE_FILE,
    NoCallForge,
    issue,
    kinds,
    make_inputs,
    pr,
)
from wgmesh_pipeline.forge.protocol import ForgeIssue
from wgmesh_pipeline.selfheal import (
    HealAction,
    assert_state_mutation,
    run_self_heal,
)


@pytest.fixture(scope="module")
def recorded_state() -> dict:
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


@pytest.fixture()
def parity_run(recorded_state):
    previous = {
        **recorded_state,
        "last_check": "2026-06-12T16:51:43Z",
        "checks_run": recorded_state["checks_run"] - 1,
    }
    return run_self_heal(
        NoCallForge(),
        make_inputs(previous_state=previous, open_prs=6),
    )


class TestParityWithRecordedState:
    """A healthy nothing-to-heal run reproduces the recorded state on main."""

    def test_state_byte_exact(self, parity_run):
        rendered = json.dumps(parity_run.state, indent=2) + "\n"
        assert rendered == STATE_FILE.read_text(encoding="utf-8")

    def test_counters_match_recorded(self, parity_run, recorded_state):
        assert parity_run.state["checks_run"] == recorded_state["checks_run"]
        assert (
            parity_run.state["issues_healed_total"]
            == recorded_state["issues_healed_total"]
        )
        assert parity_run.state["last_run_summary"] == recorded_state["last_run_summary"]

    def test_retry_tracker_carried_unchanged(self, parity_run, recorded_state):
        assert parity_run.state["retry_tracker"] == recorded_state["retry_tracker"]

    def test_healthy_run_asserts_mutation(self, parity_run):
        assert parity_run.mutation_asserted is True
        assert parity_run.state["consecutive_no_mutation_runs"] == 0
        assert parity_run.state["last_mutation_assertion"]["status"] == "passed"

    def test_no_heal_actions_planned(self, parity_run):
        assert parity_run.actions == ()
        assert parity_run.circuit_breaker_tripped is False

    def test_previous_state_not_mutated(self, recorded_state):
        previous = {**recorded_state, "last_check": "2026-06-12T16:51:43Z"}
        frozen = json.dumps(previous, sort_keys=True)
        run_self_heal(NoCallForge(), make_inputs(previous_state=previous, open_prs=6))
        assert json.dumps(previous, sort_keys=True) == frozen


class TestCircuitBreaker:
    def test_ten_escalations_trip_breaker_and_gate_later_sweeps(self, recorded_state):
        issues = tuple(issue(100 + i) for i in range(10))
        tracker = {str(100 + i): {"retries": 2} for i in range(10)}
        previous = {**recorded_state, "retry_tracker": tracker, "checks_run": 1}
        run = run_self_heal(
            NoCallForge(),
            make_inputs(
                previous_state=previous,
                stale_triage_issues=issues,
                stale_copilot_issues=(issue(660),),  # must be gated off
                needs_human_issues=(issue(700, title="budget gone"),),
            ),
        )
        assert run.circuit_breaker_tripped is True
        assert kinds(run).count("escalate") == 10
        assert "circuit_breaker" in kinds(run)
        assert "retrigger_copilot" not in kinds(run)
        assert run.state["last_run_summary"]["stale_copilot_found"] == 0
        # funnel step gated → previous funnel_signals preserved verbatim
        assert run.state["funnel_signals"] == recorded_state["funnel_signals"]
        # idle signal still computed (unconditional step)
        assert run.state["idle_signal"]["idle"] is False

    def test_breaker_issue_body_counts(self, recorded_state):
        issues = tuple(issue(100 + i) for i in range(10))
        tracker = {str(100 + i): {"retries": 2} for i in range(10)}
        run = run_self_heal(
            NoCallForge(),
            make_inputs(
                previous_state={**recorded_state, "retry_tracker": tracker},
                stale_triage_issues=issues,
            ),
        )
        breaker = next(a for a in run.actions if a.kind == "circuit_breaker")
        assert "10 issues created, 0 errors" in (breaker.body or "")


class TestAssertStateMutation:
    def test_frozen_clock_fails_assertion(self, recorded_state):
        previous = {**recorded_state, "last_check": NOW}  # last_check cannot advance
        run = run_self_heal(NoCallForge(), make_inputs(previous_state=previous, open_prs=6))
        assert run.mutation_asserted is False
        assert run.state["consecutive_no_mutation_runs"] == 1
        assert run.state["last_mutation_assertion"]["reason"] == "last_check-not-advanced"

    def test_second_consecutive_failure_escalates_supervisor_dead(self):
        state = {"last_check": NOW, "consecutive_no_mutation_runs": 1}
        updated, passed, action = assert_state_mutation(NOW, state, NOW)
        assert passed is False
        assert updated["consecutive_no_mutation_runs"] == 2
        assert isinstance(action, HealAction)
        assert action.title == "supervisor-dead: pipeline-health frozen"
        assert "consecutive_no_mutation_runs=2." in (action.body or "")

    def test_advance_resets_counter(self):
        state = {"last_check": NOW, "consecutive_no_mutation_runs": 5}
        updated, passed, action = assert_state_mutation("2026-06-12T16:00:00Z", state, NOW)
        assert passed is True and action is None
        assert updated["consecutive_no_mutation_runs"] == 0


class TestEveryDetectorFires:
    def test_all_sweeps_act_in_one_run(self, recorded_state):
        previous = {**recorded_state, "retry_tracker": {}, "checks_run": 10,
                    "issues_healed_total": 5, "last_check": "2026-06-12T16:00:00Z"}
        run = run_self_heal(
            NoCallForge(),
            make_inputs(
                previous_state=previous,
                stale_triage_issues=(issue(651),),
                stale_copilot_issues=(issue(660),),
                stale_approved_prs=(pr(667, "spec: Issue #650"),),
                needs_human_issues=(issue(700, title="x"),),
                linked_merged_pr_counts={700: 1},
                open_prs=3,
            ),
        )
        assert kinds(run) == [
            "retrigger_triage", "retrigger_copilot", "retrigger_goose",
            "close_needs_human",
        ]
        summary = run.state["last_run_summary"]
        assert summary == {
            "stale_triage_found": 1, "stale_copilot_found": 1, "stale_approved_found": 1,
            "needs_human_closed": 1, "actions_taken": 4, "errors": 0,
        }
        assert run.state["issues_healed_total"] == 9  # 5 + 4
        assert run.state["checks_run"] == 11
        assert set(run.state["retry_tracker"]) == {"651", "660", "pr-667"}
        assert run.mutation_asserted is True


class _ReadOnlyForge:
    """Exposes ONLY the read the runner may use; any write blows up."""

    def __init__(self, issues: list[ForgeIssue]) -> None:
        self._issues = issues

    def list_open_issues(self) -> list[ForgeIssue]:
        return self._issues

    def __getattr__(self, name: str):
        raise AssertionError(f"runner must not call forge.{name} in parity phase")


class TestForgeFallback:
    def test_needs_human_derived_from_forge_when_input_missing(self):
        forge = _ReadOnlyForge([
            ForgeIssue(number=700, title="x", labels=("needs-human",), state="open"),
            ForgeIssue(number=701, title="y", labels=("needs-human",), state="open",
                       pull_request={"url": "z"}),  # PRs filtered out
            ForgeIssue(number=702, title="z", labels=("bug",), state="open"),
        ])
        run = run_self_heal(
            forge,
            make_inputs(
                needs_human_issues=None, linked_merged_pr_counts={700: 1}, open_prs=1
            ),
        )
        assert kinds(run) == ["close_needs_human"]
        assert run.actions[0].number == 700

    def test_idle_run_with_empty_previous_state(self):
        run = run_self_heal(NoCallForge(), make_inputs(open_prs=0))
        assert run.state["checks_run"] == 1
        assert run.state["issues_healed_total"] == 0
        assert run.state["idle_signal"]["idle"] is True
        assert kinds(run) == ["dispatch_observation_loop"]
        assert run.mutation_asserted is True  # empty prev → first check still advances
