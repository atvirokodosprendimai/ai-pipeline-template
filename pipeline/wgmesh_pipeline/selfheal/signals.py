"""Self-Heal signals + state: funnel/dogfood/presence, idle detection, the
idle observation-loop dispatch, the state summary, and the state-mutation
assertion (cutover U4). Pure decisions — no forge writes.
"""

from __future__ import annotations

from typing import Any, Mapping

from wgmesh_pipeline.selfheal.models import (
    ACTIVE_PIPELINE_LABELS,
    CHECK_INTERVAL_HOURS,
    IDLE_DISPATCH_COOLDOWN_SECONDS,
    SUPERVISOR_DEAD_TITLE,
    HealAction,
    SelfHealInputs,
    audit_entry,
    labels_joined,
    parse_iso,
)


def check_funnel_signals(inputs: SelfHealInputs) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dogfood + presence signals → (funnel_signals state value, audit entry)."""
    text = inputs.claude_md_text or ""
    dogfood = bool(text) and ("architecture" in text.lower()) and ("build" in text.lower())
    details: list[str] = []
    presence = bool(inputs.endpoints)
    for endpoint in inputs.endpoints:
        ok = 200 <= int(endpoint.get("status") or 0) < 400
        details.append(f"{endpoint.get('name')}:{'ok' if ok else 'fail'}")
        presence = presence and ok
    checked_at = inputs.signals_now or inputs.now
    signals = {
        "dogfood": dogfood, "presence": presence,
        "endpoint_details": ",".join(details), "checked_at": checked_at,
    }
    entry = audit_entry(
        checked_at, inputs.run_id, "check_funnel_signals", None,
        "periodic signal check", None, signals={"dogfood": dogfood, "presence": presence},
    )
    return signals, entry


def check_idle_signal(
    inputs: SelfHealInputs, actions_taken: int, errors: int
) -> dict[str, Any]:
    """Idle detector — open PRs + active-pipeline-labelled issues + this run.
    Label match here is EXACT (jq ``any(.labels[].name; . == …)``), unlike
    the grep-substring checks in the sweeps."""
    active = sum(
        1 for issue in inputs.open_issues
        if any(name in ACTIVE_PIPELINE_LABELS for name in labels_joined(issue).split(","))
    )
    idle = inputs.open_prs == 0 and active == 0 and actions_taken == 0 and errors == 0
    signal: dict[str, Any] = {
        "idle": idle, "open_prs": inputs.open_prs, "active_pipeline_issues": active,
        "checked_at": inputs.signals_now or inputs.now,
    }
    last_dispatch = str(
        (inputs.previous_state.get("idle_signal") or {}).get("last_dispatch_at") or ""
    )
    if last_dispatch:
        signal["last_dispatch_at"] = last_dispatch
    return signal


def decide_idle_dispatch(
    idle_signal: Mapping[str, Any], now: str
) -> tuple[HealAction | None, dict[str, Any]]:
    """Observation-loop dispatch on idle, behind the 6h cooldown."""
    signal = dict(idle_signal)
    if not signal.get("idle"):
        return None, signal
    last = str(signal.get("last_dispatch_at") or "")
    if last:
        try:
            elapsed = (parse_iso(now) - parse_iso(last)).total_seconds()
        except ValueError:
            elapsed = None  # unparseable → shell fell back to epoch 0 (dispatch)
        if elapsed is not None and elapsed < IDLE_DISPATCH_COOLDOWN_SECONDS:
            return None, signal
    action = HealAction(
        kind="dispatch_observation_loop", target="repo",
        body=f"signal=idle-pipeline source=pipeline-health idle_checked_at={now}",
        reason="idle pipeline",
    )
    return action, {**signal, "last_dispatch_at": now}


def build_state(
    previous_state: Mapping[str, Any],
    *,
    now: str,
    retry_tracker: Mapping[str, Any],
    funnel_signals: Mapping[str, Any],
    idle_signal: Mapping[str, Any],
    stale_triage_found: int,
    stale_copilot_found: int,
    stale_approved_found: int,
    needs_human_closed: int,
    actions_taken: int,
    errors: int,
) -> dict[str, Any]:
    """State summary — key order byte-compatible with the workflow's jq -n."""
    return {
        "last_check": now,
        "check_interval_hours": CHECK_INTERVAL_HOURS,
        "checks_run": int(previous_state.get("checks_run") or 0) + 1,
        "issues_healed_total": int(previous_state.get("issues_healed_total") or 0)
        + actions_taken,
        "consecutive_no_mutation_runs": int(
            previous_state.get("consecutive_no_mutation_runs") or 0
        ),
        "retry_tracker": dict(retry_tracker),
        "funnel_signals": dict(funnel_signals),
        "idle_signal": dict(idle_signal),
        "last_run_summary": {
            "stale_triage_found": stale_triage_found,
            "stale_copilot_found": stale_copilot_found,
            "stale_approved_found": stale_approved_found,
            "needs_human_closed": needs_human_closed,
            "actions_taken": actions_taken,
            "errors": errors,
        },
    }


def assert_state_mutation(
    pre_run_last_check: str, state: Mapping[str, Any], now: str
) -> tuple[dict[str, Any], bool, HealAction | None]:
    """Port of assert-state-mutation.sh: returns (state', passed, escalation).

    Pass: ``last_check`` advanced → counter resets, assertion recorded.
    Fail: counter increments; at >=2 consecutive failures the supervisor-dead
    needs-human escalation is planned (create-or-comment is the executor's
    concern). Never silent — the runner surfaces the verdict either way.
    """
    post = str(state.get("last_check") or "")
    if post and post != pre_run_last_check:
        passed_state = {
            **state,
            "consecutive_no_mutation_runs": 0,
            "last_mutation_asserted_at": now,
            "last_mutation_assertion": {"status": "passed", "checked_at": now},
        }
        return passed_state, True, None
    count = int(state.get("consecutive_no_mutation_runs") or 0) + 1
    failed_state = {
        **state,
        "consecutive_no_mutation_runs": count,
        "last_mutation_asserted_at": now,
        "last_mutation_assertion": {
            "status": "failed", "reason": "last_check-not-advanced", "checked_at": now,
        },
    }
    action: HealAction | None = None
    if count >= 2:
        action = HealAction(
            kind="supervisor_dead", target="issue", title=SUPERVISOR_DEAD_TITLE,
            body=(
                "pipeline-health did not prove state mutation. "
                f"Reason: last_check-not-advanced. consecutive_no_mutation_runs={count}."
            ),
            add_label="needs-human", reason="last_check-not-advanced",
        )
    return failed_state, False, action
