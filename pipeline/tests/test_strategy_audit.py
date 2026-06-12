"""Strategy-audit parity + edge-case tests (cutover U6).

Parity fixtures replay recorded Actions runs against the on-main
``company/strategy-audit-baseline.json``:

  - The latest run (2026-06-12, drift PR #1677 "audit: strategy drift
    detected ae5123115cb0") must reproduce verdict, fingerprint, and the
    12-char title hash byte-exact, and the updated baseline's
    ``last_reported_drift_fingerprint`` must equal what the run's marker
    committed to main (the value recorded in the baseline file today).
  - The 2026-06-10 run (drift PR #1624 "audit: strategy drift detected
    0ba6becc8c61") pins a metric-drift fingerprint hash.
  - The 2026-06-11 commit_main run must append an audit entry byte-identical
    (including key order) to the recorded ``audits[-1]``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wgmesh_pipeline.strategy_audit import (
    FIRST_RUN_FINGERPRINT,
    MAX_AUDITS,
    MetricRow,
    append_audit,
    decide,
    drift_fingerprint,
    extract_paid_customers,
    fingerprint_hash,
    metric_row,
    milestone_status,
    parse_milestones,
    run_strategy_audit,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
# FROZEN fixture (same lesson as #1691): the live baseline mutates on every
# strategy-audit cron run; parity pins the recorded copy.
BASELINE_FILE = Path(__file__).parent / "fixtures" / "strategy_audit_baseline.json"
STRATEGY_FILE = REPO_ROOT / "STRATEGY.md"

# Milestones section frozen as of the recorded runs (matches the recorded
# audits' milestone targets byte-for-byte; the real STRATEGY.md may evolve).
STRATEGY_FIXTURE = """\
# STRATEGY

## Milestones

- **2026-05-10** — first audit-loop closes cleanly (drift PR opens, founder applies, doc updates, audit re-runs green)
- **2026-05-17** — wgmesh edge node beta (first seeded product reaches public beta)
- **2026-05-31** — 1 paying customer
- **2026-06-14** — 2nd seed product spec'd and entering convergence engine
- **2026-08-31** — 4 customers ($10K ARR run-rate path)
- **2027-05-03** — 42 customers, $10K ARR
- **2028-05-03** — 420 customers, $100K ARR (MSC)

## Next section
"""

# Fingerprint the 2026-06-10 run reported (drift PR #1624) — the value
# last_reported held when the 06-11 and 06-12 runs executed.
FP_STUCK = "metrics=active_stuck_issues;overdue_milestones=2026-05-31"
# Fingerprint the latest run reported (drift PR #1677, 2026-06-12).
FP_OVERDUE_ONLY = "metrics=;overdue_milestones=2026-05-31"

METRICS_2026_06_11 = {
    "paid_customers": 0,
    "autonomous_ship_rate": None,
    "lead_time_hours": 154.77,
    "self_heal_rate": 0,
    "active_stuck_issues": 1,
}


@pytest.fixture(scope="module")
def recorded() -> dict:
    return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- parity


def test_parity_latest_run_verdict_and_fingerprint(recorded: dict) -> None:
    """Replay the 2026-06-12 run that opened drift PR #1677."""
    pre_run = {**recorded, "last_reported_drift_fingerprint": FP_STUCK}
    run = run_strategy_audit(
        pre_run,
        metrics=METRICS_2026_06_11,  # 06-12 measured the same values
        strategy_text=STRATEGY_FIXTURE,
        now="2026-06-12T12:17:20Z",
    )
    assert run.fingerprint == FP_OVERDUE_ONLY
    # PR #1677 title: "audit: strategy drift detected ae5123115cb0"
    assert run.fingerprint_hash == "ae5123115cb0"
    assert run.any_drift is True
    assert run.decision.action == "open_pr"
    assert run.material_changed is True
    # The marker the run committed to main is what the file records today.
    assert (
        run.baseline["last_reported_drift_fingerprint"]
        == recorded["last_reported_drift_fingerprint"]
    )
    # Metric table from the PR body: all OK / NO DATA, deltas 0% / n/a.
    assert [(r.verdict, r.delta_display) for r in run.metric_rows] == [
        ("OK", "0%"),
        ("NO DATA", "n/a"),
        ("OK", "0%"),
        ("OK", "0%"),
        ("OK", "0%"),
        ("NO DATA", "n/a"),
    ]
    # Milestone table from the PR body.
    assert [m.status for m in run.milestones] == [
        "pending-uncertain",
        "pending-uncertain",
        "overdue",
        "pending",
        "pending",
        "pending",
        "pending",
    ]


def test_parity_prior_run_metric_drift_hash(recorded: dict) -> None:
    """Replay the 2026-06-10 run that opened drift PR #1624."""
    pre_run = {
        "audits": recorded["audits"][:5],  # through the 2026-06-09 entry
        "last_reported_drift_fingerprint": FP_OVERDUE_ONLY,
    }
    run = run_strategy_audit(
        pre_run,
        metrics=METRICS_2026_06_11,  # active_stuck_issues went 0 -> 1
        strategy_text=STRATEGY_FIXTURE,
        now="2026-06-10T12:18:50Z",
    )
    assert run.fingerprint == FP_STUCK
    # PR #1624 title: "audit: strategy drift detected 0ba6becc8c61"
    assert run.fingerprint_hash == "0ba6becc8c61"
    assert run.decision.action == "open_pr"
    drifted = [r.key for r in run.metric_rows if r.drift]
    assert drifted == ["active_stuck_issues"]


def test_parity_appended_entry_byte_exact(recorded: dict) -> None:
    """Replay the 2026-06-11 commit_main run; the appended audit entry must
    be byte-identical (key order included) to the recorded audits[-1]."""
    pre_run = {
        "audits": recorded["audits"][:5],
        "last_reported_drift_fingerprint": FP_STUCK,
    }
    run = run_strategy_audit(
        pre_run,
        metrics=METRICS_2026_06_11,
        strategy_text=STRATEGY_FIXTURE,
        now="2026-06-11T12:43:01Z",
    )
    # Drift fingerprint repeats the already-reported one -> no new PR; the
    # metric values changed (stuck 0 -> 1) -> baseline telemetry commit.
    assert run.decision.action == "commit_main"
    assert run.decision.open_pr is False
    assert run.material_changed is True
    assert len(run.baseline["audits"]) == 6
    expected = recorded["audits"][-1]
    actual = run.baseline["audits"][-1]
    assert actual == expected
    # Byte-exact including key order (what jq persisted on main).
    assert json.dumps(actual, indent=2) == json.dumps(expected, indent=2)
    # last_reported carries over unchanged on commit_main.
    assert run.baseline["last_reported_drift_fingerprint"] == FP_STUCK


# ----------------------------------------------------------------- edges


def _baseline_with_metrics(metrics: dict, fingerprint: str) -> dict:
    return {
        "audits": [{"ran_at": "2026-05-01T00:00:00Z", "metrics": dict(metrics)}],
        "last_reported_drift_fingerprint": fingerprint,
    }


def test_no_drift_no_value_change_skips() -> None:
    metrics = {**METRICS_2026_06_11, "active_stuck_issues": 0}
    previous = {**metrics, "cycle_time_to_revenue": None}
    baseline = _baseline_with_metrics(previous, "metrics=;overdue_milestones=")
    run = run_strategy_audit(
        baseline,
        metrics=metrics,
        strategy_text=STRATEGY_FIXTURE,
        now="2026-05-09T00:00:00Z",  # before any milestone date
    )
    assert run.any_drift is False
    assert run.fingerprint == "metrics=;overdue_milestones="
    assert run.decision.action == "skip"
    assert run.material_changed is False
    # Input baseline not mutated (immutability).
    assert len(baseline["audits"]) == 1


def test_all_null_metrics_no_data_everywhere() -> None:
    nulls = {key: None for key in METRICS_2026_06_11}
    previous = {**nulls, "cycle_time_to_revenue": None}
    baseline = _baseline_with_metrics(previous, "metrics=;overdue_milestones=")
    run = run_strategy_audit(
        baseline,
        metrics=nulls,
        strategy_text=STRATEGY_FIXTURE,
        now="2026-05-09T00:00:00Z",
        paid_fetch_status="fetch_failed",
    )
    assert all(r.verdict == "NO DATA" and r.drift is False for r in run.metric_rows)
    assert run.any_drift is False
    assert run.decision.action == "skip"
    # Null paid count renders the workflow's literal "null paid customers".
    customer_rows = [m for m in run.milestones if "paying customer" in m.target]
    assert customer_rows and customer_rows[0].current == "null paid customers"
    entry = run.baseline["audits"][-1]
    assert entry["metrics"]["fetch_status"]["paid_customers"] == "fetch_failed"


def test_first_run_never_flags_drift() -> None:
    run = run_strategy_audit(
        {"audits": []},
        metrics=METRICS_2026_06_11,
        strategy_text=STRATEGY_FIXTURE,
        now="2026-06-12T00:00:00Z",  # 2026-05-31 milestone is overdue
    )
    assert run.first_run is True
    assert run.any_drift is False
    assert run.fingerprint == FIRST_RUN_FINGERPRINT
    # The seeded baseline still commits (metric values appeared).
    assert run.decision.action == "commit_main"
    assert run.material_changed is True
    assert len(run.baseline["audits"]) == 1


def test_overdue_milestone_boundary() -> None:
    milestones = [("2026-06-12", "1 paying customer")]
    # Due today + target unmet -> overdue (bash: today >= date).
    assert milestone_status(milestones, "2026-06-12", 0)[0].status == "overdue"
    # Due tomorrow -> still pending.
    assert milestone_status(milestones, "2026-06-11", 0)[0].status == "pending"
    # Target met -> met, even past the date.
    assert milestone_status(milestones, "2026-07-01", 1)[0].status == "met"
    # Non-customer milestone past due -> pending-uncertain, never overdue.
    other = [("2026-06-12", "edge node beta ships")]
    assert milestone_status(other, "2026-06-12", 0)[0].status == "pending-uncertain"


def test_metric_row_threshold_boundaries() -> None:
    # grow: delta exactly +10% drifts (>=); just under does not.
    assert metric_row("m", "M", "grow", 10, 11).drift is True
    assert metric_row("m", "M", "grow", 10, 10.9).drift is False
    # drop: delta exactly -10% drifts (<=); a drop on a "grow" metric does not.
    assert metric_row("m", "M", "drop", 10, 9).drift is True
    assert metric_row("m", "M", "grow", 10, 9).drift is False
    # zero baseline clamps the denominator at 0.0001 (0 -> 1 is huge drift).
    row = metric_row("m", "M", "grow", 0, 1)
    assert row.drift is True and row.delta == pytest.approx(10000.0)
    # display formatting mirrors jq tostring (+ sign, integral floats bare).
    assert metric_row("m", "M", "grow", 10, 11).delta_display == "+10%"
    assert metric_row("m", "M", "drop", 10, 9).delta_display == "-10%"


def test_fingerprint_stability_and_idempotent_rerun() -> None:
    rows = (
        metric_row("active_stuck_issues", "Active stuck issues", "grow", 0, 1),
        metric_row("lead_time_hours", "Lead time hours", "grow", 5.0, 50.0),
    )
    milestones = milestone_status(
        [("2026-05-31", "1 paying customer"), ("2026-04-30", "2 customers")],
        "2026-06-12",
        0,
    )
    fp = drift_fingerprint(rows, milestones)
    # Sorted + unique, independent of input order.
    assert fp == (
        "metrics=active_stuck_issues,lead_time_hours"
        ";overdue_milestones=2026-04-30,2026-05-31"
    )
    assert drift_fingerprint(tuple(reversed(rows)), tuple(reversed(milestones))) == fp
    assert fingerprint_hash(fp) == fingerprint_hash(fp)
    assert drift_fingerprint(rows, milestones, first_run=True) == FIRST_RUN_FINGERPRINT

    # Re-running on the runner's own output with identical inputs is a no-op.
    first = run_strategy_audit(
        {"audits": []},
        metrics=METRICS_2026_06_11,
        strategy_text=STRATEGY_FIXTURE,
        now="2026-05-09T00:00:00Z",
    )
    second = run_strategy_audit(
        first.baseline,
        metrics=METRICS_2026_06_11,
        strategy_text=STRATEGY_FIXTURE,
        now="2026-05-09T01:00:00Z",
    )
    assert second.fingerprint == first.fingerprint
    assert second.decision.action == "skip"
    assert second.material_changed is False


def test_decide_requires_new_fingerprint_for_pr() -> None:
    """The dedupe contract: a repeated drift fingerprint never re-opens."""
    baseline = {"audits": [], "last_reported_drift_fingerprint": FP_OVERDUE_ONLY}
    candidate = append_audit(baseline, {"ran_at": "x", "metrics": {}})
    decision, updated = decide(baseline, candidate, True, FP_OVERDUE_ONLY)
    assert decision.action == "skip" and decision.open_pr is False
    assert updated["last_reported_drift_fingerprint"] == FP_OVERDUE_ONLY
    decision, updated = decide(baseline, candidate, True, FP_STUCK)
    assert decision.action == "open_pr"
    assert updated["last_reported_drift_fingerprint"] == FP_STUCK


def test_append_audit_caps_and_does_not_mutate() -> None:
    baseline = {"audits": [{"ran_at": str(i)} for i in range(MAX_AUDITS)]}
    updated = append_audit(baseline, {"ran_at": "new"})
    assert len(updated["audits"]) == MAX_AUDITS
    assert updated["audits"][-1]["ran_at"] == "new"
    assert updated["audits"][0]["ran_at"] == "1"  # oldest dropped
    assert len(baseline["audits"]) == MAX_AUDITS  # input untouched


def test_metrics_input_validation() -> None:
    with pytest.raises(ValueError, match="active_stuck_issues"):
        run_strategy_audit(
            {"audits": []},
            metrics={**METRICS_2026_06_11, "active_stuck_issues": "1"},
            strategy_text=STRATEGY_FIXTURE,
            now="2026-06-12T00:00:00Z",
        )


# ------------------------------------------------- sourced reads (plan §U6)


def test_parse_milestones_reads_real_strategy_md() -> None:
    parsed = parse_milestones(STRATEGY_FILE.read_text(encoding="utf-8"))
    assert len(parsed) >= 1
    for date_part, target in parsed:
        assert len(date_part) == 10 and target


def test_extract_paid_customers_from_chimney_html() -> None:
    html = (
        '<div class="stage-metric">Paid subscriber</div>\n'
        '<div class="stage-status">3</div>\n'
    )
    assert extract_paid_customers(html) == 3
    assert extract_paid_customers("<html>no signal</html>") is None
    # Count on the same line as the label still extracts.
    assert extract_paid_customers("Paid subscribers: 7") == 7
