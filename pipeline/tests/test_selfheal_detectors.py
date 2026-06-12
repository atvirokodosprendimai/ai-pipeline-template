"""Self-Heal detector edge cases (cutover U4): the three stale sweeps, the
needs-human resolution signals, and the funnel/idle signal functions.
Runner-level + parity tests live in ``test_selfheal.py``.
"""

from __future__ import annotations

import json

import pytest

from selfheal_fixtures import (
    ENDPOINTS_OK,
    FRESH,
    NOW,
    STALE,
    NoCallForge,
    issue,
    kinds,
    make_inputs,
    pr,
)
from wgmesh_pipeline.selfheal import (
    check_funnel_signals,
    decide_idle_dispatch,
    run_self_heal,
    sweep_needs_human,
    sweep_stale_approved,
    sweep_stale_copilot,
    sweep_stale_triage,
)


class TestStaleTriageSweep:
    def test_first_failure_retriggers_labels(self):
        inputs = make_inputs(stale_triage_issues=(issue(651),))
        outcome = sweep_stale_triage(inputs, {})
        action = outcome.actions[0]
        assert (action.kind, action.remove_label, action.add_label) == (
            "retrigger_triage", "needs-triage", "needs-triage"
        )
        assert outcome.retry_tracker["651"] == {
            "retries": 1, "last_retry": NOW, "action": "retrigger_triage",
        }
        assert (outcome.stale_found, outcome.actions_taken, outcome.issues_created) == (1, 1, 0)

    def test_two_failures_escalates_needs_human_with_cooldown(self):
        tracker = {"651": {"retries": 2, "last_retry": STALE, "action": "retrigger_triage"}}
        outcome = sweep_stale_triage(make_inputs(stale_triage_issues=(issue(651),)), tracker)
        action = outcome.actions[0]
        assert action.kind == "escalate"
        assert action.title == "[needs-human] Stuck at triage: #651"
        assert action.body == (
            "Self-healing failed to resolve stale triage for #651 after 2 attempts."
        )
        # escalate only ADDS cooldown_until (retries/last_retry preserved)
        assert outcome.retry_tracker["651"] == {
            "retries": 2, "last_retry": STALE, "action": "retrigger_triage",
            "cooldown_until": "2026-06-13T17:21:49Z",
        }
        assert outcome.issues_created == 1

    def test_cooldown_skips_but_counts_stale(self):
        tracker = {"651": {"retries": 2, "cooldown_until": "2026-06-13T00:00:00Z"}}
        outcome = sweep_stale_triage(make_inputs(stale_triage_issues=(issue(651),)), tracker)
        assert outcome.actions == ()
        assert outcome.stale_found == 1

    def test_expired_cooldown_heal_replaces_entry_dropping_cooldown(self):
        tracker = {"651": {"retries": 1, "cooldown_until": "2026-06-01T00:00:00Z"}}
        outcome = sweep_stale_triage(make_inputs(stale_triage_issues=(issue(651),)), tracker)
        assert outcome.actions[0].kind == "retrigger_triage"
        assert "cooldown_until" not in outcome.retry_tracker["651"]
        assert outcome.retry_tracker["651"]["retries"] == 2

    def test_skips_before_stale_count(self):
        inputs = make_inputs(
            stale_triage_issues=(
                issue(1, labels=("manual-only",)),
                issue(2, labels=("wont-do",)),
                issue(3, labels=("needs-info", "bug")),
                issue(4),  # completed: merged resolution PR exists
                issue(5, created=FRESH),  # not past cutoff
            ),
            merged_resolution_issues=frozenset({4}),
        )
        outcome = sweep_stale_triage(inputs, {})
        assert outcome.stale_found == 0
        assert outcome.actions == ()

    def test_malformed_tracker_raises_loudly(self):
        with pytest.raises(ValueError, match="malformed retry_tracker"):
            sweep_stale_triage(
                make_inputs(stale_triage_issues=(issue(651),)), {"651": "garbage"}
            )

    def test_audit_lines_byte_compatible_with_jq(self):
        outcome = sweep_stale_triage(make_inputs(stale_triage_issues=(issue(651),)), {})
        line = json.dumps(outcome.audit[0], separators=(",", ":"))
        assert line == (
            '{"timestamp":"2026-06-12T17:21:49Z","run_id":"run-1",'
            '"action":"retrigger_triage","issue_number":651,"target_repo":"wgmesh",'
            '"reason":"stale >24h at needs-triage","outcome":"success","retry_count":1}'
        )


class TestStaleCopilotSweep:
    def test_heal_swaps_copilot_label_for_needs_triage(self):
        outcome = sweep_stale_copilot(make_inputs(stale_copilot_issues=(issue(660),)), {})
        action = outcome.actions[0]
        assert (action.kind, action.remove_label, action.add_label) == (
            "retrigger_copilot", "copilot-triaging", "needs-triage"
        )

    def test_open_spec_pr_skips_after_stale_count(self):
        inputs = make_inputs(
            stale_copilot_issues=(issue(660),), open_spec_pr_issues=frozenset({660})
        )
        outcome = sweep_stale_copilot(inputs, {})
        assert outcome.stale_found == 1  # counted, then skipped
        assert outcome.actions == ()

    def test_48h_cutoff_excludes_two_day_old_issue(self):
        outcome = sweep_stale_copilot(
            make_inputs(stale_copilot_issues=(issue(661, created="2026-06-11T00:00:00Z"),)),
            {},
        )
        assert outcome.stale_found == 0


class TestStaleApprovedSweep:
    def test_tracker_keyed_pr_prefix_and_goose_retrigger(self):
        outcome = sweep_stale_approved(
            make_inputs(stale_approved_prs=(pr(667, "spec: Issue #650 - mesh"),)), {}
        )
        assert outcome.actions[0].kind == "retrigger_goose"
        assert outcome.actions[0].target == "pr"
        assert "pr-667" in outcome.retry_tracker

    def test_open_impl_pr_skips_after_count(self):
        inputs = make_inputs(
            stale_approved_prs=(pr(667, "spec: Issue #650 - mesh"),),
            open_impl_pr_issues=frozenset({650}),
        )
        outcome = sweep_stale_approved(inputs, {})
        assert outcome.stale_found == 1
        assert outcome.actions == ()

    def test_escalation_title_and_reason(self):
        tracker = {"pr-667": {"retries": 2}}
        outcome = sweep_stale_approved(
            make_inputs(stale_approved_prs=(pr(667, "spec: Issue #650"),)), tracker
        )
        assert outcome.actions[0].title == "[needs-human] Stuck at build: PR #667"
        assert outcome.audit[0]["reason"] == "2 consecutive build trigger failures"


class TestNeedsHumanSweep:
    def test_linked_merged_pr_closes(self):
        inputs = make_inputs(
            needs_human_issues=(issue(700, title="anything"),),
            linked_merged_pr_counts={700: 2},
        )
        outcome = sweep_needs_human(inputs)
        assert outcome.actions[0].comment == (
            "Resolved by self-healing: Linked PR merged (2 merged PR(s) found)"
        )
        assert outcome.closed == 1

    def test_api_key_title_resolved_by_running_loop(self):
        inputs = make_inputs(
            needs_human_issues=(issue(701, title="Missing API key for loop"),),
            loop_state={"last_run": "2026-06-12T00:00:00Z", "run_count": 41},
        )
        outcome = sweep_needs_human(inputs)
        assert "run_count=41" in outcome.actions[0].reason

    def test_health_title_resolved_when_all_endpoints_ok(self):
        inputs = make_inputs(needs_human_issues=(issue(702, title="Health endpoint down"),))
        assert sweep_needs_human(inputs).actions[0].reason == (
            "All health endpoints responding OK"
        )

    def test_health_title_unresolved_when_endpoint_fails(self):
        bad = ENDPOINTS_OK[:3] + ({"name": "tvcentras", "status": 503},)
        inputs = make_inputs(
            needs_human_issues=(issue(702, title="Health endpoint down"),), endpoints=bad
        )
        assert sweep_needs_human(inputs).actions == ()

    def test_budget_title_resolved_by_integer_capital_only(self):
        item = issue(703, title="burn rate exceeds budget")
        ok = make_inputs(
            needs_human_issues=(item,), costs={"runway": {"available_capital": 9000}}
        )
        assert "available_capital=9000" in sweep_needs_human(ok).actions[0].reason
        floaty = make_inputs(
            needs_human_issues=(item,), costs={"runway": {"available_capital": 9000.5}}
        )
        assert sweep_needs_human(floaty).actions == ()  # shell -gt is integer-only

    def test_no_signal_and_manual_only_skip(self):
        inputs = make_inputs(
            needs_human_issues=(
                issue(704, title="mystery failure"),
                issue(705, title="health alarm", labels=("manual-only",)),
            ),
        )
        assert sweep_needs_human(inputs).actions == ()


class TestSignals:
    def test_dogfood_requires_architecture_and_build(self):
        signals, _ = check_funnel_signals(make_inputs(claude_md_text="## Architecture only"))
        assert signals["dogfood"] is False
        signals, _ = check_funnel_signals(make_inputs())
        assert signals["dogfood"] is True

    def test_presence_false_and_details_on_failing_endpoint(self):
        bad = ENDPOINTS_OK[:1] + ({"name": "cloudroof", "status": 500},)
        signals, entry = check_funnel_signals(make_inputs(endpoints=bad))
        assert signals["presence"] is False
        assert signals["endpoint_details"] == "chimney:ok,cloudroof:fail"
        assert entry["signals"] == {"dogfood": True, "presence": False}

    def test_no_endpoints_means_no_presence(self):
        signals, _ = check_funnel_signals(make_inputs(endpoints=()))
        assert signals["presence"] is False
        assert signals["endpoint_details"] == ""

    def test_idle_dispatch_fires_once_then_cools_down_6h(self):
        idle = {"idle": True, "open_prs": 0, "active_pipeline_issues": 0, "checked_at": NOW}
        action, updated = decide_idle_dispatch(idle, NOW)
        assert action is not None and action.kind == "dispatch_observation_loop"
        assert updated["last_dispatch_at"] == NOW
        again, kept = decide_idle_dispatch(updated, "2026-06-12T19:21:49Z")  # 2h later
        assert again is None
        assert kept["last_dispatch_at"] == NOW
        later, bumped = decide_idle_dispatch(updated, "2026-06-13T00:21:49Z")  # 7h later
        assert later is not None
        assert bumped["last_dispatch_at"] == "2026-06-13T00:21:49Z"

    def test_not_idle_never_dispatches(self):
        action, _ = decide_idle_dispatch({"idle": False}, NOW)
        assert action is None

    def test_runner_idle_run_plans_dispatch(self):
        run = run_self_heal(NoCallForge(), make_inputs(open_prs=0))
        assert run.state["idle_signal"]["idle"] is True
        assert kinds(run) == ["dispatch_observation_loop"]
        assert run.state["idle_signal"]["last_dispatch_at"] == NOW

    def test_active_pipeline_label_is_exact_match(self):
        issues = (
            issue(1, labels=("needs-triage-extra",)),  # NOT active (exact match)
            issue(2, labels=("goose-implementation",)),
        )
        run = run_self_heal(NoCallForge(), make_inputs(open_prs=0, open_issues=issues))
        assert run.state["idle_signal"]["active_pipeline_issues"] == 1
        assert run.state["idle_signal"]["idle"] is False
