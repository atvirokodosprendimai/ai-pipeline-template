from __future__ import annotations

import json
from pathlib import Path

from wgmesh_pipeline.gtm_lane.executor import ItemStatus
from wgmesh_pipeline.gtm_lane.telemetry import record_outcome


def test_records_status_counts_and_cost(tmp_path: Path) -> None:
    state = tmp_path / "gtm-execution-state.json"
    record_outcome(ItemStatus.CLOSED, state_path=state, cost=0.4)
    record_outcome(ItemStatus.CLOSED, state_path=state, cost=0.6)
    record_outcome(ItemStatus.ESCALATED, state_path=state)
    data = json.loads(state.read_text())
    assert data["counts"]["closed"] == 2
    assert data["counts"]["escalated"] == 1
    assert data["total_cost"] == 0.4 + 0.6


def test_write_failure_is_best_effort(tmp_path: Path) -> None:
    # an unwritable path must NOT raise — telemetry must never block the lane
    bad = tmp_path / "nonexistent-dir" / "state.json"  # parent missing
    # should silently no-op, not raise
    record_outcome(ItemStatus.CLOSED, state_path=bad, cost=1.0, make_parents=False)


def test_records_latency_when_given(tmp_path: Path) -> None:
    state = tmp_path / "s.json"
    record_outcome(ItemStatus.CLOSED, state_path=state, cost=0.1, latency_s=12.5)
    data = json.loads(state.read_text())
    assert data["last_latency_s"] == 12.5
