"""Box-side Strategy-Drift Audit: metric drift, milestones, baseline, fingerprint.

Port of the Actions ``strategy-audit`` workflow (cutover plan U6): the
``metric_row`` jq function, the STRATEGY.md milestone parser/status loop, and
``.github/scripts/strategy-audit-gate.sh`` (drift fingerprint, metric-values
gate, decide) collapse into pure functions; ``run_strategy_audit`` is a thin
runner over plain-dict inputs. Semantics are ported, not redesigned — the
0.0001 denominator clamp, jq rounding, date string-compare, and the
``metrics=...;overdue_milestones=...`` fingerprint are byte-compatible
(parity-tested against the recorded ``company/strategy-audit-baseline.json``
and drift PRs #1624/#1677).

CRITICAL design note — dedupe, don't stack: the Actions version opened one
drift PR per run, piling near-identical drift PRs (#1624/#1677 both closed
reasoned as that anti-pattern). ``run_strategy_audit`` therefore performs NO
GitHub writes: it RETURNS the updated baseline dict plus a drift verdict,
exposing ``material_changed`` + ``fingerprint`` so the future caller dedupes
— ``decision.action == "open_pr"`` only when the fingerprint is NEW versus
``last_reported_drift_fingerprint``; ``material_changed`` False = do nothing.

Caller-side (mirror the workflow): gathering input metrics (gh-based reads,
chimney HTTP fetch — only the pure ``extract_paid_customers`` parse lives
here) and the ``company/scripts/sanitise.sh`` wall before any persist.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

DRIFT_THRESHOLD = 0.10
MAX_AUDITS = 365
FIRST_RUN_FINGERPRINT = "metrics=;overdue_milestones="
CYCLE_TIME_FETCH_STATUS = "no_customers"

# (key, label, direction) in the exact emission order of the workflow.
METRIC_SPECS: tuple[tuple[str, str, str], ...] = (
    ("paid_customers", "Paid customers", "drop"),
    ("autonomous_ship_rate", "Autonomous-ship rate", "drop"),
    ("lead_time_hours", "Lead time hours", "grow"),
    ("self_heal_rate", "Self-heal rate", "drop"),
    ("active_stuck_issues", "Active stuck issues", "grow"),
    ("cycle_time_to_revenue", "Cycle time to revenue (hours)", "grow"),
)

# Caller-supplied keys; cycle_time_to_revenue is synthesized null (declared
# in STRATEGY.md but not yet computable — no Polar webhook).
INPUT_METRIC_KEYS: tuple[str, ...] = tuple(key for key, _, _ in METRIC_SPECS[:-1])


_MILESTONE_DATE_RE = re.compile(r"^- \*\*(\d{4}-\d{2}-\d{2})\*\* .*")
_MILESTONE_TARGET_RE = re.compile(r"^- \*\*[0-9-]+\*\* . (.*)$")
_CUSTOMER_TARGET_RE = re.compile(r"paying customer|customers", re.IGNORECASE)
_FIRST_INT_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class MetricRow:
    """One metric verdict — mirrors the fields the ``metric_row`` jq emits."""

    key: str
    label: str
    baseline: float | int | None
    current: float | int | None
    delta: float | None
    pct_abs: float | None
    delta_display: str
    verdict: str  # "OK" | "DRIFT" | "NO DATA"
    drift: bool


@dataclass(frozen=True)
class MilestoneStatus:
    """One STRATEGY.md milestone row, as persisted in ``milestones_status``."""

    date: str
    target: str
    current: str
    status: str  # "pending" | "pending-uncertain" | "overdue" | "met"

    def as_dict(self) -> dict[str, str]:
        return {
            "date": self.date,
            "target": self.target,
            "current": self.current,
            "status": self.status,
        }


@dataclass(frozen=True)
class AuditDecision:
    """Outcome of ``decide`` — port of ``strategy_audit_decide``'s env file."""

    action: str  # "open_pr" | "commit_main" | "skip"
    open_pr: bool
    commit_main: bool
    metric_values_changed: bool
    fingerprint: str
    last_reported: str


@dataclass(frozen=True)
class StrategyAuditRun:
    """Runner outcome: verdict + the updated baseline dict the caller may
    persist. ``material_changed`` is the dedupe sentinel: when False the
    caller must NOT persist ``baseline`` nor open anything (anti pile-up)."""

    ran_at: str
    first_run: bool
    metric_rows: tuple[MetricRow, ...]
    milestones: tuple[MilestoneStatus, ...]
    any_drift: bool
    fingerprint: str
    fingerprint_hash: str
    decision: AuditDecision
    baseline: dict[str, Any]
    material_changed: bool


def _jq_round(value: float) -> float:
    """jq ``round`` — half away from zero (C round), not banker's rounding."""
    if value >= 0:
        return math.floor(value + 0.5)
    return math.ceil(value - 0.5)


def _format_number(value: float | int) -> str:
    """jq ``tostring`` for numbers: integral floats print without ``.0``."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def metric_row(
    key: str,
    label: str,
    direction: str,
    baseline: float | int | None,
    current: float | int | None,
    threshold: float = DRIFT_THRESHOLD,
) -> MetricRow:
    """One metric drift verdict — exact port of the workflow's ``metric_row`` jq."""
    if direction not in ("drop", "grow"):
        raise ValueError(f"metric_row: direction must be drop|grow, got {direction!r}")
    if baseline is None or current is None:
        return MetricRow(key, label, baseline, current, None, None, "n/a", "NO DATA", False)
    absb = abs(baseline)
    denom = 0.0001 if absb < 0.0001 else absb
    delta = (current - baseline) / denom
    pct = _jq_round(delta * 1000) / 10
    pct_abs = -pct if pct < 0 else pct
    drift = (direction == "drop" and delta <= -threshold) or (
        direction == "grow" and delta >= threshold
    )
    delta_display = ("+" if pct > 0 else "") + _format_number(pct) + "%"
    verdict = "DRIFT" if drift else "OK"
    return MetricRow(key, label, baseline, current, delta, pct_abs, delta_display, verdict, drift)


def evaluate_metrics(
    previous_metrics: Mapping[str, Any] | None,
    current_metrics: Mapping[str, Any],
    threshold: float = DRIFT_THRESHOLD,
) -> tuple[MetricRow, ...]:
    """All metric rows in the workflow's emission order (METRIC_SPECS)."""
    previous = previous_metrics or {}
    return tuple(
        metric_row(key, label, direction, previous.get(key), current_metrics.get(key), threshold)
        for key, label, direction in METRIC_SPECS
    )


def parse_milestones(strategy_text: str) -> tuple[tuple[str, str], ...]:
    """(date, target) pairs from STRATEGY.md's ``## Milestones`` section —
    port of the awk section filter + sed date/target extraction."""
    in_section = False
    parsed: list[tuple[str, str]] = []
    for line in strategy_text.splitlines():
        if line.startswith("## Milestones"):
            in_section = True
            continue
        if line.startswith("## "):
            in_section = False
        if not (in_section and line.startswith("- ")):
            continue
        date_match = _MILESTONE_DATE_RE.match(line)
        if not date_match:
            continue
        target_match = _MILESTONE_TARGET_RE.match(line)
        parsed.append((date_match.group(1), target_match.group(1) if target_match else ""))
    return tuple(parsed)


def milestone_status(
    milestones: Sequence[tuple[str, str]],
    today: str,
    paid_customers: float | int | None,
) -> tuple[MilestoneStatus, ...]:
    """Status per milestone — exact port of the workflow's milestone loop.
    Customer-count milestones compare against ``paid_customers``; any other
    milestone past its date is ``pending-uncertain`` (calendar reminder, never
    drift). Date compare is YYYY-MM-DD string order, ``today >= date``."""
    statuses: list[MilestoneStatus] = []
    for date_part, target in milestones:
        current = "not measured"
        status = "pending"
        if _CUSTOMER_TARGET_RE.search(target):
            num_match = _FIRST_INT_RE.search(target)
            target_num = int(num_match.group(0)) if num_match else None
            paid_display = "null" if paid_customers is None else _format_number(paid_customers)
            current = f"{paid_display} paid customers"
            if paid_customers is not None and target_num is not None and paid_customers >= target_num:
                status = "met"
            elif today >= date_part:
                status = "overdue"
        elif today >= date_part:
            status = "pending-uncertain"
        statuses.append(MilestoneStatus(date_part, target, current, status))
    return tuple(statuses)


def drift_fingerprint(
    rows: Sequence[MetricRow],
    milestones: Sequence[MilestoneStatus],
    first_run: bool = False,
) -> str:
    """``metrics=...;overdue_milestones=...`` — port of
    ``strategy_audit_drift_fingerprint`` (unique+sorted keys/dates)."""
    if first_run:
        return FIRST_RUN_FINGERPRINT
    metric_keys = sorted({row.key for row in rows if row.verdict == "DRIFT" or row.drift})
    overdue_dates = sorted({m.date for m in milestones if m.status == "overdue"})
    return "metrics=" + ",".join(metric_keys) + ";overdue_milestones=" + ",".join(overdue_dates)


def fingerprint_hash(fingerprint: str) -> str:
    """First 12 hex chars of sha256 — the workflow's branch/title suffix."""
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]


def extract_paid_customers(html: str) -> int | None:
    """Paid-subscriber count from the chimney dashboard HTML — port of
    ``grep -i -A 1 'Paid subscriber' | grep -oE '[0-9]+' | head -n 1``.
    The fetch itself stays with the caller; this is the pure parse."""
    lines = html.splitlines()
    window: list[str] = []
    for index, line in enumerate(lines):
        if "paid subscriber" in line.lower():
            window.append(line)
            if index + 1 < len(lines):
                window.append(lines[index + 1])
    match = _FIRST_INT_RE.search("\n".join(window))
    return int(match.group(0)) if match else None


def build_metrics_record(
    metrics: Mapping[str, Any], paid_fetch_status: str
) -> dict[str, Any]:
    """The ``metrics`` object persisted per audit entry, exact key order.
    ``cycle_time_to_revenue`` is always null (not yet computable)."""
    for key in INPUT_METRIC_KEYS:
        value = metrics.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"metric {key} must be a number or None, got {value!r}")
    return {
        "paid_customers": metrics.get("paid_customers"),
        "autonomous_ship_rate": metrics.get("autonomous_ship_rate"),
        "lead_time_hours": metrics.get("lead_time_hours"),
        "self_heal_rate": metrics.get("self_heal_rate"),
        "active_stuck_issues": metrics.get("active_stuck_issues"),
        "cycle_time_to_revenue": None,
        "fetch_status": {
            "paid_customers": str(paid_fetch_status),
            "cycle_time_to_revenue": CYCLE_TIME_FETCH_STATUS,
        },
    }


def append_audit(baseline: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    """New baseline dict with ``entry`` appended to ``audits`` (capped at
    the trailing MAX_AUDITS, jq ``.[-365:]``). Inputs are not mutated."""
    audits = list(baseline.get("audits") or [])
    audits.append(dict(entry))
    return {**baseline, "audits": audits[-MAX_AUDITS:]}


def _latest_metric_values(state: Mapping[str, Any]) -> dict[str, Any]:
    audits = state.get("audits") or []
    last: Mapping[str, Any] = audits[-1] if audits else {}
    metrics = dict((last or {}).get("metrics") or {})
    metrics.pop("fetch_status", None)
    return metrics


def metric_values_changed(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> bool:
    """Did the latest audit's metric VALUES change (fetch_status excluded)?
    Port of ``strategy_audit_metric_values_changed``."""
    return _latest_metric_values(baseline) != _latest_metric_values(candidate)


def decide(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    any_drift: bool,
    fingerprint: str,
) -> tuple[AuditDecision, dict[str, Any]]:
    """Port of ``strategy_audit_decide``: open_pr only on a NEW drift
    fingerprint; commit_main on metric-value change; otherwise skip. Returns
    decision + candidate with ``last_reported_drift_fingerprint`` updated."""
    last_reported = str(baseline.get("last_reported_drift_fingerprint") or "")
    values_changed = metric_values_changed(baseline, candidate)

    action = "skip"
    open_pr = False
    commit_main = False
    output_fingerprint = last_reported
    if any_drift and fingerprint != last_reported:
        action = "open_pr"
        open_pr = True
        output_fingerprint = fingerprint
    elif values_changed:
        action = "commit_main"
        commit_main = True

    updated = {**candidate, "last_reported_drift_fingerprint": output_fingerprint}
    decision = AuditDecision(
        action=action,
        open_pr=open_pr,
        commit_main=commit_main,
        metric_values_changed=values_changed,
        fingerprint=fingerprint,
        last_reported=last_reported,
    )
    return decision, updated


def run_strategy_audit(
    baseline: Mapping[str, Any],
    *,
    metrics: Mapping[str, Any],
    strategy_text: str,
    paid_fetch_status: str = "ok",
    now: str | None = None,
    threshold: float = DRIFT_THRESHOLD,
) -> StrategyAuditRun:
    """Evaluate drift, build the audit entry, and return verdict + updated
    baseline. NO GitHub writes — persisting ``baseline`` (only when
    ``material_changed``, through the sanitise wall) and any PR/anchor
    side effect keyed on ``decision``/``fingerprint`` stay with the caller.

    ``metrics`` is a plain dict with INPUT_METRIC_KEYS (numbers or None);
    ``strategy_text`` is the STRATEGY.md content; ``now`` is an ISO-8601 UTC
    timestamp (``today`` for milestone checks derives from its date part).
    """
    ran_at = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = ran_at[:10]

    audits = baseline.get("audits") or []
    first_run = len(audits) == 0
    previous: Mapping[str, Any] = (audits[-1] if audits else {}) or {}

    record = build_metrics_record(metrics, paid_fetch_status)
    rows = evaluate_metrics(previous.get("metrics"), record, threshold)
    milestones = milestone_status(
        parse_milestones(strategy_text), today, record["paid_customers"]
    )

    # First run never flags drift (workflow zeroes both counts).
    metric_drift_count = 0 if first_run else sum(1 for row in rows if row.drift)
    overdue_count = 0 if first_run else sum(1 for m in milestones if m.status == "overdue")
    any_drift = metric_drift_count > 0 or overdue_count > 0
    fingerprint = drift_fingerprint(rows, milestones, first_run)

    entry = {
        "ran_at": ran_at,
        "metrics": record,
        "milestones_status": [m.as_dict() for m in milestones],
    }
    candidate = append_audit(baseline, entry)
    decision, updated = decide(baseline, candidate, any_drift, fingerprint)

    return StrategyAuditRun(
        ran_at=ran_at,
        first_run=first_run,
        metric_rows=rows,
        milestones=milestones,
        any_drift=any_drift,
        fingerprint=fingerprint,
        fingerprint_hash=fingerprint_hash(fingerprint),
        decision=decision,
        baseline=updated,
        material_changed=decision.action != "skip",
    )
