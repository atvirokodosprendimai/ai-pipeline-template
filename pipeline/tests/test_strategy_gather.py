from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wgmesh_pipeline.control_loop.executor import EXECUTED
from wgmesh_pipeline.observation import ObservationAction
from wgmesh_pipeline.state.store import StateStore
from wgmesh_pipeline.strategy_audit import INPUT_METRIC_KEYS
from wgmesh_pipeline.strategy_gather import (
    STRATEGY_AUDIT_CHIMNEY_URL,
    build_strategy_drift_action,
    extract_paid_customers,
    gather_strategy_metrics,
    run_strategy_cycle,
)


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    labels: tuple[str, ...]
    state: str = "open"
    pull_request: dict[str, Any] | None = None


class Response:
    def __init__(self, text: str, *, raises: bool = False) -> None:
        self.text = text
        self.raises = raises

    def raise_for_status(self) -> None:
        if self.raises:
            raise RuntimeError("http failed")


class MetricsForge:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def list_open_issues(self) -> list[Issue]:
        return [
            Issue(1, "human", ("needs-human",)),
            Issue(2, "normal", ("fn:dev",)),
        ]

    def list_recent_merged_prs(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {
                "number": 10,
                "author": {"login": "goose[bot]"},
                "mergedAt": "2026-06-14T12:00:00Z",
                "closingIssuesReferences": [{"number": 1}],
                "comments": [],
                "reviews": [],
                "labels": [],
            },
            {
                "number": 11,
                "author": {"login": "human"},
                "mergedAt": "2026-06-14T13:00:00Z",
                "closingIssuesReferences": [],
                "comments": [],
                "reviews": [],
                "labels": [],
            },
        ]

    def issue_labeled_at(self, issue_number: int, label: str) -> str | None:
        assert (issue_number, label) == (1, "needs-triage")
        return "2026-06-14T00:00:00Z"

    def create_issue(self, **kwargs: Any) -> dict[str, Any]:
        self.created.append(kwargs)
        return {"dry_run": True}


class NoOptionalSourcesForge:
    def list_open_issues(self) -> list[Issue]:
        return [Issue(1, "human", ("needs-human",))]


def test_extract_paid_customers_is_reexported_for_chimney_fixture() -> None:
    html = """
    <div>Paid subscriber</div>
    <div class="stage-status">4</div>
    """
    assert extract_paid_customers(html) == 4


def test_gather_strategy_metrics_maps_all_input_metric_keys(tmp_path) -> None:
    db = StateStore(tmp_path / "state.db")
    db.save_control_state(
        "pipeline-health-state",
        {
            "last_run_summary": {"actions_taken": 3, "needs_human_closed": 1},
            "retry_tracker": {"1": {"cooldown_until": "2026-06-16T00:00:00Z"}},
        },
        fingerprint="heal",
    )

    result = gather_strategy_metrics(
        MetricsForge(),
        db,
        http_get=lambda url, timeout: Response("Paid subscribers\n5"),
        now="2026-06-15T00:00:00Z",
    )

    assert set(result.metrics) == set(INPUT_METRIC_KEYS)
    assert result.metrics["self_heal_rate"] == 0.75
    assert result.metrics["active_stuck_issues"] == 2
    assert result.metrics["lead_time_hours"] == 12.0
    assert result.metrics["autonomous_ship_rate"] == 1.0
    assert result.metrics["paid_customers"] == 5
    assert result.paid_fetch_status == "ok"


def test_absent_sources_degrade_to_none_without_crashing(tmp_path) -> None:
    db = StateStore(tmp_path / "state.db")
    result = gather_strategy_metrics(
        NoOptionalSourcesForge(),
        db,
        http_get=lambda url, timeout: Response("", raises=True),
        now="2026-06-15T00:00:00Z",
    )

    assert result.metrics["self_heal_rate"] is None
    assert result.metrics["active_stuck_issues"] == 1
    assert result.metrics["lead_time_hours"] is None
    assert result.metrics["autonomous_ship_rate"] is None
    assert result.metrics["paid_customers"] is None
    assert result.paid_fetch_status == "failed"


def test_chimney_fetch_uses_timeout_and_default_url(tmp_path) -> None:
    seen: list[tuple[str, int]] = []

    def http_get(url: str, timeout: int) -> Response:
        seen.append((url, timeout))
        return Response("Paid subscriber\n9")

    gather_strategy_metrics(
        NoOptionalSourcesForge(), StateStore(tmp_path / "state.db"), http_get=http_get
    )

    assert seen == [(STRATEGY_AUDIT_CHIMNEY_URL, 15)]


def test_material_changed_persists_and_unchanged_fingerprint_does_not_write(
    tmp_path,
) -> None:
    db = StateStore(tmp_path / "state.db")
    forge = NoOptionalSourcesForge()

    first = run_strategy_cycle(
        forge,
        db,
        strategy_text="last_updated: 2026-06-15\n\n## Milestones\n",
        http_get=lambda url, timeout: Response("Paid subscriber\n1"),
        now="2026-06-15T00:00:00Z",
    )
    second = run_strategy_cycle(
        forge,
        db,
        strategy_text="last_updated: 2026-06-15\n\n## Milestones\n",
        http_get=lambda url, timeout: Response("Paid subscriber\n1"),
        now="2026-06-15T00:00:00Z",
    )

    assert first.persisted is True
    assert db.load_control_state("strategy-audit-baseline") is not None
    assert second.persisted is False


def test_open_pr_drift_routes_through_executor_dry_run(tmp_path) -> None:
    db = StateStore(tmp_path / "state.db")
    db.save_control_state(
        "strategy-audit-baseline",
        {
            "audits": [
                {
                    "ran_at": "2026-06-14T00:00:00Z",
                    "metrics": {
                        "paid_customers": 10,
                        "autonomous_ship_rate": 1.0,
                        "lead_time_hours": 1,
                        "self_heal_rate": 1.0,
                        "active_stuck_issues": 0,
                        "cycle_time_to_revenue": None,
                        "fetch_status": {
                            "paid_customers": "ok",
                            "cycle_time_to_revenue": "no_customers",
                        },
                    },
                    "milestones_status": [],
                }
            ],
            "last_reported_drift_fingerprint": "old",
        },
        fingerprint="old",
    )
    forge = MetricsForge()

    result = run_strategy_cycle(
        forge,
        db,
        strategy_text="last_updated: 2026-06-15\n\n## Milestones\n",
        http_get=lambda url, timeout: Response("Paid subscriber\n1"),
        now="2026-06-15T00:00:00Z",
    )

    assert result.run.decision.action == "open_pr"
    assert [r.status for r in result.execution_results] == [EXECUTED]
    assert forge.created
    assert isinstance(build_strategy_drift_action(result.run), ObservationAction)
