"""Live metric gather for the box-side strategy audit cycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any, Callable, Iterable, Mapping, Sequence

import requests

from wgmesh_pipeline.control_loop import SELFHEAL_STATE_KEY, STRATEGY_AUDIT_STATE_KEY
from wgmesh_pipeline.control_loop.executor import ExecutionResult, execute_actions
from wgmesh_pipeline.forge.protocol import Forge
from wgmesh_pipeline.observation import ObservationAction
from wgmesh_pipeline.strategy_audit import (
    INPUT_METRIC_KEYS,
    StrategyAuditRun,
    extract_paid_customers,
    run_strategy_audit,
)

log = logging.getLogger("wgmesh_pipeline.strategy_gather")

STRATEGY_AUDIT_CHIMNEY_URL = "https://chimney.beerpub.dev/"
BOT_AUTHORS = frozenset({"goose[bot]", "copilot-swe-agent[bot]", "pupabobas[bot]"})

HttpGet = Callable[..., Any]


@dataclass(frozen=True)
class StrategyMetricsResult:
    metrics: dict[str, float | int | None]
    paid_fetch_status: str


@dataclass(frozen=True)
class StrategyCycleResult:
    metrics: StrategyMetricsResult
    run: StrategyAuditRun
    execution_results: tuple[ExecutionResult, ...]
    persisted: bool


def gather_strategy_metrics(
    forge: Forge,
    store: Any,
    *,
    http_get: HttpGet = requests.get,
    now: str | None = None,
) -> StrategyMetricsResult:
    current = now or _utc_now_iso()
    metrics: dict[str, float | int | None] = {key: None for key in INPUT_METRIC_KEYS}
    heal_state = _load_state(store, SELFHEAL_STATE_KEY)
    metrics["self_heal_rate"] = _self_heal_rate(heal_state)
    try:
        metrics["active_stuck_issues"] = _active_stuck_issues(
            forge, heal_state, now=current
        )
    except Exception as exc:  # noqa: BLE001 - degraded metric, never crash
        log.warning(
            "control_loop: strategy_audit active_stuck_issues unavailable: %s", exc
        )
        metrics["active_stuck_issues"] = None

    lead_time, autonomous_rate = _merged_pr_metrics(forge)
    metrics["lead_time_hours"] = lead_time
    metrics["autonomous_ship_rate"] = autonomous_rate

    paid, paid_status = _paid_customers(http_get)
    metrics["paid_customers"] = paid
    return StrategyMetricsResult(metrics=metrics, paid_fetch_status=paid_status)


def run_strategy_cycle(
    forge: Forge,
    store: Any,
    *,
    strategy_text: str,
    http_get: HttpGet = requests.get,
    now: str | None = None,
    executor: Callable[
        [Forge, Any, Sequence[Any]], list[ExecutionResult]
    ] = execute_actions,
) -> StrategyCycleResult:
    gathered = gather_strategy_metrics(forge, store, http_get=http_get, now=now)
    baseline = _load_state(store, STRATEGY_AUDIT_STATE_KEY) or {}
    run = run_strategy_audit(
        baseline,
        metrics=gathered.metrics,
        strategy_text=strategy_text,
        paid_fetch_status=gathered.paid_fetch_status,
        now=now,
    )
    persisted = False
    if run.material_changed:
        persisted = _save_state(
            store, STRATEGY_AUDIT_STATE_KEY, run.baseline, run.fingerprint
        )
    actions: tuple[ObservationAction, ...] = ()
    if run.decision.action == "open_pr":
        actions = (build_strategy_drift_action(run),)
    results = tuple(executor(forge, store, actions))
    statuses = [result.status for result in results]
    log.info(
        "control_loop: module=strategy_audit decision=%s material_changed=%s "
        "planned_actions=%s executed=%s result_statuses=%s persisted=%s paid_fetch_status=%s",
        run.decision.action,
        run.material_changed,
        len(actions),
        sum(1 for status in statuses if status == "executed"),
        statuses[:5],
        persisted,
        gathered.paid_fetch_status,
    )
    return StrategyCycleResult(gathered, run, results, persisted)


def build_strategy_drift_action(run: StrategyAuditRun) -> ObservationAction:
    rows = "\n".join(
        f"- {row.label}: baseline={row.baseline}, current={row.current}, "
        f"delta={row.delta_display}, verdict={row.verdict}"
        for row in run.metric_rows
    )
    milestones = "\n".join(
        f"- {item.date}: {item.target} ({item.current}, {item.status})"
        for item in run.milestones
    )
    body = (
        f"Drift fingerprint: `{run.fingerprint}`\n\n"
        "## Metric drift\n"
        f"{rows or '- none'}\n\n"
        "## Milestone status\n"
        f"{milestones or '- none'}\n\n"
        "_Created by the control-loop strategy audit gatherer._"
    )
    return ObservationAction(
        kind="create_issue",
        title=f"audit: strategy drift detected {run.fingerprint_hash}",
        body=body,
        labels=("needs-human",),
        reason=run.fingerprint,
    )


def _load_state(store: Any, key: str) -> Mapping[str, Any] | None:
    loader = getattr(store, "load_control_state", None)
    if loader is None:
        return None
    try:
        loaded = loader(key)
    except Exception as exc:  # noqa: BLE001 - degraded metric/state
        log.warning(
            "control_loop: strategy_audit load_control_state(%s) failed: %s", key, exc
        )
        return None
    return loaded if isinstance(loaded, Mapping) else None


def _save_state(store: Any, key: str, doc: Mapping[str, Any], fingerprint: str) -> bool:
    saver = getattr(store, "save_control_state", None)
    if saver is None:
        return False
    try:
        return bool(saver(key, dict(doc), fingerprint=fingerprint))
    except Exception as exc:  # noqa: BLE001 - never abort audit on persistence failure
        log.warning(
            "control_loop: strategy_audit save_control_state(%s) failed: %s", key, exc
        )
        return False


def _self_heal_rate(state: Mapping[str, Any] | None) -> float | None:
    if not state:
        return None
    summary = state.get("last_run_summary")
    if not isinstance(summary, Mapping):
        return None
    actions = _number(summary.get("actions_taken"))
    closed = _number(summary.get("needs_human_closed"))
    if actions is None or closed is None:
        return None
    total = actions + closed
    return 0.0 if total == 0 else actions / total


def _active_stuck_issues(
    forge: Forge, state: Mapping[str, Any] | None, *, now: str
) -> int:
    needs_human = sum(
        1
        for issue in forge.list_open_issues()
        if "needs-human" in tuple(str(label) for label in issue.labels)
        and not getattr(issue, "pull_request", None)
    )
    return needs_human + _cooldown_count(state, now=now)


def _cooldown_count(state: Mapping[str, Any] | None, *, now: str) -> int:
    if not state:
        return 0
    tracker = state.get("retry_tracker") or {}
    entries: Iterable[Any]
    if isinstance(tracker, Mapping):
        entries = tracker.values()
    elif isinstance(tracker, list):
        entries = tracker
    else:
        return 0
    count = 0
    for entry in entries:
        if isinstance(entry, Mapping) and str(entry.get("cooldown_until") or "") > now:
            count += 1
    return count


def _merged_pr_metrics(forge: Forge) -> tuple[float | None, float | None]:
    reader = getattr(forge, "list_recent_merged_prs", None)
    if reader is None:
        return None, None
    try:
        prs = reader(limit=100)
    except TypeError:
        prs = reader()
    except Exception as exc:  # noqa: BLE001 - degraded metric, never crash
        log.warning("control_loop: strategy_audit merged PR list unavailable: %s", exc)
        return None, None
    if not isinstance(prs, list):
        return None, None
    return _lead_time_hours(forge, prs), _autonomous_ship_rate(prs)


def _lead_time_hours(forge: Forge, prs: Sequence[Mapping[str, Any]]) -> float | None:
    label_reader = getattr(forge, "issue_labeled_at", None)
    if label_reader is None:
        return None
    hours: list[float] = []
    for pr in prs:
        merged_at = str(pr.get("mergedAt") or pr.get("merged_at") or "")
        for issue in (
            pr.get("closingIssuesReferences") or pr.get("closing_issues") or []
        ):
            number = _issue_number(issue)
            if number is None:
                continue
            try:
                labeled_at = label_reader(number, "needs-triage")
            except (
                Exception
            ) as exc:  # noqa: BLE001 - one missing timeline degrades that PR
                log.warning(
                    "control_loop: strategy_audit labeled-at unavailable: %s", exc
                )
                continue
            delta = _hours_between(str(labeled_at or ""), merged_at)
            if delta is not None:
                hours.append(delta)
    return None if not hours else float(median(hours))


def _autonomous_ship_rate(prs: Sequence[Mapping[str, Any]]) -> float | None:
    bot_total = 0
    clean = 0
    for pr in prs:
        if _author_login(pr.get("author")) not in BOT_AUTHORS:
            continue
        bot_total += 1
        if _is_clean_bot_pr(pr):
            clean += 1
    return None if bot_total == 0 else round(clean / bot_total, 4)


def _is_clean_bot_pr(pr: Mapping[str, Any]) -> bool:
    labels = pr.get("labels") or []
    if any(_label_name(label) == "needs-human" for label in labels):
        return False
    comments = pr.get("comments") or []
    reviews = pr.get("reviews") or []
    non_bot_comments = [
        _author_login(c.get("author")) for c in comments if isinstance(c, Mapping)
    ]
    non_bot_reviews = [
        _author_login(r.get("author"))
        for r in reviews
        if isinstance(r, Mapping) and str(r.get("body") or "")
    ]
    return all(_is_bot_login(login) for login in non_bot_comments + non_bot_reviews)


def _paid_customers(http_get: HttpGet) -> tuple[int | None, str]:
    try:
        response = http_get(STRATEGY_AUDIT_CHIMNEY_URL, timeout=15)
        response.raise_for_status()
        paid = extract_paid_customers(str(response.text))
    except Exception as exc:  # noqa: BLE001 - degraded metric
        log.warning("control_loop: strategy_audit chimney fetch failed: %s", exc)
        return None, "failed"
    if paid is None:
        log.warning("control_loop: strategy_audit chimney paid customer parse failed")
        return None, "failed"
    return paid, "ok"


def _issue_number(issue: Any) -> int | None:
    try:
        if isinstance(issue, Mapping):
            value = issue.get("number")
            return None if value is None else int(value)
        return int(issue)
    except (TypeError, ValueError):
        return None


def _author_login(author: Any) -> str:
    if isinstance(author, Mapping):
        return str(author.get("login") or "")
    return str(author or "")


def _label_name(label: Any) -> str:
    if isinstance(label, Mapping):
        return str(label.get("name") or "")
    return str(label or "")


def _is_bot_login(login: str) -> bool:
    return not login or login.endswith("[bot]") or login in BOT_AUTHORS


def _hours_between(start: str, end: str) -> float | None:
    try:
        start_dt = _parse_iso(start)
        end_dt = _parse_iso(end)
    except ValueError:
        return None
    seconds = (end_dt - start_dt).total_seconds()
    if seconds < 0:
        return None
    return round(seconds / 3600, 2)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
