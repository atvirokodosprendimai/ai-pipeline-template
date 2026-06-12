"""Observation-loop deterministic-half tests (cutover U3).

Covers the #1665 close-guard matrix, the dedup guard (exact stop-word port,
2-hit threshold, head-5 quirks), the action-plan builder, and the documented
caller-side sanitise-gate expectation. ALL fixtures are FROZEN literals in
this file — never read mutable state files from the tree (lesson #1691).
"""

from __future__ import annotations

import pytest

from wgmesh_pipeline.observation import (
    CLOSE_REASON_NOT_PLANNED,
    STOP_WORDS,
    ObservationAction,
    ObservationInputs,
    ObservationPlan,
    build_dedup_corpus,
    build_open_board,
    extract_keywords,
    is_duplicate,
    plan_actions,
    vet_issue_close,
)

# ── Frozen fixtures ─────────────────────────────────────────────────

INPUTS = ObservationInputs(
    open_issue_titles=(
        "Review burn rate alerts for the pipeline",
        "wgmesh release blocked on key rotation",
    ),
    closed_issue_titles=(
        "Implement peer handshake retry backoff",
    ),
    issue_labels={
        652: ("needs-human", "blocked"),
        700: ("bug",),
        701: (),
        702: ("enhancement", "stale"),
    },
)


def _close(number, reason):
    return {"number": number, "reason": reason}


# ── #1665 close-guard matrix ───────────────────────────────────────

def test_needs_human_close_skipped():
    action, skip = vet_issue_close(_close(652, "obsolete"), INPUTS.issue_labels)
    assert action is None
    assert skip.code == "needs_human_label"
    assert skip.number == 652
    assert "human-lane only" in skip.message


def test_label_fetch_failure_skipped_fail_closed():
    # Missing number in the snapshot == the workflow's failed `gh issue view`.
    action, skip = vet_issue_close(_close(999, "done"), INPUTS.issue_labels)
    assert action is None
    assert skip.code == "label_fetch_failed"
    assert "refusing to close blind" in skip.message


def test_explicit_none_labels_skipped_fail_closed():
    action, skip = vet_issue_close(_close(700, "done"), {700: None})
    assert action is None
    assert skip.code == "label_fetch_failed"


def test_malformed_number_skipped_fail_closed():
    # jq -r '.number' on a missing key yields "null"; gh issue view "null"
    # fails the label fetch -> the close is refused, not attempted.
    action, skip = vet_issue_close({"reason": "done"}, INPUTS.issue_labels)
    assert action is None
    assert skip.code == "label_fetch_failed"


@pytest.mark.parametrize("reason", [
    "Relabel rather than close",
    "should be REOPENED with a fresh spec",
    "relabel to needs-human instead",
])
def test_contradicting_reason_skipped(reason):
    action, skip = vet_issue_close(_close(700, reason), INPUTS.issue_labels)
    assert action is None
    assert skip.code == "reason_contradicts_close"
    assert reason in skip.message


def test_legit_close_is_not_planned():
    action, skip = vet_issue_close(_close(700, "superseded by #800"), INPUTS.issue_labels)
    assert skip is None
    assert action.kind == "close_issue"
    assert action.number == 700
    # Guard 3 (R5): never COMPLETED on a non-merge signal.
    assert action.close_reason == CLOSE_REASON_NOT_PLANNED
    assert action.comment == "Closed by observation loop: superseded by #800"


def test_needs_human_substring_label_does_not_trip_guard():
    # The workflow greps ",needs-human," in ",$labels," — element-exact.
    action, skip = vet_issue_close(
        _close(700, "done"), {700: ("needs-humanoid",)})
    assert skip is None
    assert action.kind == "close_issue"


# ── Dedup matrix ────────────────────────────────────────────────────

def test_stopword_filtering_ported_exactly():
    assert extract_keywords("Fix the burn rate for the pipeline") == (
        "burn", "rate", "pipeline")
    # Every workflow stop word, no more, no fewer.
    assert STOP_WORDS == frozenset((
        "the", "a", "an", "in", "on", "for", "to", "of", "and", "or", "is",
        "set", "add", "configure", "verify", "check", "update", "review",
        "approve", "implement", "basic", "define", "fix", "enable"))


def test_keyword_cap_is_five():
    assert extract_keywords("alpha beta gamma delta epsilon zeta eta") == (
        "alpha", "beta", "gamma", "delta", "epsilon")


def test_leading_non_alnum_consumes_a_head_slot():
    # tr quirk kept: leading "[" yields an empty first line which head -5
    # counts; shell word-splitting later drops it from matching.
    assert extract_keywords("[spec] alpha beta gamma delta epsilon") == (
        "", "spec", "alpha", "beta", "gamma")


def test_two_keyword_hits_on_one_title_is_duplicate():
    # "configure"/"review" are stop words; burn+rate+alerts hit 3x.
    assert is_duplicate("Configure burn rate alerts",
                        ["Review burn rate alerts for the pipeline"])


def test_single_hit_is_not_duplicate():
    assert not is_duplicate("burn barrel cleanup", ["Review burn rate alerts"])


def test_hits_must_land_on_a_single_title():
    # One hit on each of two titles never reaches the 2-hit threshold.
    assert not is_duplicate("burn handshake", ["burn alerts", "peer handshake"])


def test_corpus_includes_closed_titles():
    corpus = build_dedup_corpus(INPUTS)
    assert corpus == [
        "Review burn rate alerts for the pipeline",
        "wgmesh release blocked on key rotation",
        "Implement peer handshake retry backoff",
    ]
    # Institutional learning (wgmesh#458): a closed feature dedups a re-ask.
    assert is_duplicate("peer handshake retry timer", corpus)


# ── Action-plan builder ─────────────────────────────────────────────

def test_empty_assessment_plans_nothing():
    plan = plan_actions({}, INPUTS)
    assert plan == ObservationPlan(actions=(), skips=())


def test_duplicate_create_is_skipped():
    plan = plan_actions(
        {"issues_to_create": [
            {"title": "Update burn rate alerts thresholds", "body": "b", "labels": ["ops"]}]},
        INPUTS)
    assert plan.actions == ()
    assert plan.skips[0].code == "duplicate"
    assert plan.skips[0].message == "Skipping duplicate: Update burn rate alerts thresholds"


def test_fresh_create_is_planned():
    plan = plan_actions(
        {"issues_to_create": [
            {"title": "Expose mesh telemetry endpoint", "body": "details",
             "labels": ["needs-triage"]}]},
        INPUTS)
    assert plan.skips == ()
    assert plan.actions == (ObservationAction(
        kind="create_issue", title="Expose mesh telemetry endpoint",
        body="details", labels=("needs-triage",)),)


def test_same_run_self_dedup():
    # Second identical ask dedups against the first create in the SAME run
    # (workflow appends each created title to /tmp/open_issues.txt).
    plan = plan_actions(
        {"issues_to_create": [
            {"title": "Expose mesh telemetry endpoint", "body": "x", "labels": []},
            {"title": "Expose mesh telemetry endpoint v2", "body": "y", "labels": []}]},
        INPUTS)
    assert len(plan.actions) == 1
    assert plan.skips[0].code == "duplicate"


def test_create_without_title_fails_loud():
    with pytest.raises(ValueError):
        plan_actions({"issues_to_create": [{"body": "no title"}]}, INPUTS)


def test_needs_human_create_shape_and_dedup():
    plan = plan_actions(
        {"needs_human": [
            {"request": "Rotate the observer API key", "reason": "expired",
             "urgency": "blocking"},
            {"request": "rotate observer api key again", "reason": "r",
             "urgency": "high"}]},
        INPUTS)
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.kind == "create_needs_human"
    assert action.title == "[needs-human] Rotate the observer API key"
    assert action.labels == ("needs-human",)
    assert action.body == ("**Urgency**: blocking\n\n**Reason**: expired\n\n"
                           "_Created by observation loop._")
    # Dedup keys on the REQUEST text but appends the full [needs-human] title.
    assert plan.skips[0].message == (
        "Skipping duplicate needs-human: rotate observer api key again")


def test_pr_close_action_org_prefixed_no_guards():
    plan = plan_actions(
        {"prs_to_close": [{"repo": "wgmesh", "number": 41, "reason": "stale spec"}]},
        INPUTS)
    assert plan.actions == (ObservationAction(
        kind="close_pr", repo="atvirokodosprendimai/wgmesh", number=41,
        comment="Closed by observation loop: stale spec", reason="stale spec"),)


def test_full_assessment_keeps_workflow_step_order():
    plan = plan_actions(
        {"issues_to_create": [{"title": "Expose mesh telemetry", "body": "b", "labels": []}],
         "issues_to_close": [_close(700, "superseded"), _close(652, "obsolete")],
         "needs_human": [{"request": "Approve spend cap", "reason": "r", "urgency": "high"}],
         "prs_to_close": [{"repo": "wgmesh", "number": 9, "reason": "dup"}]},
        INPUTS)
    assert [a.kind for a in plan.actions] == [
        "create_issue", "close_issue", "create_needs_human", "close_pr"]
    assert [s.code for s in plan.skips] == ["needs_human_label"]


# ── Input assembly ──────────────────────────────────────────────────

def test_open_board_format():
    board = build_open_board(
        [{"number": 1, "title": "alpha", "labels": [{"name": "bug"}, "ops"]}],
        [{"number": 2, "title": "beta", "author": {"login": "goose"}}],
        {"chimney": [{"number": 3, "title": "gamma"}], "lighthouse": []},
    )
    assert board == (
        "## Open Issues (wgmesh)\n\n- #1 alpha [bug, ops]\n\n"
        "## Open PRs (wgmesh)\n\n- PR #2 beta (by goose)\n\n"
        "## Open Issues (chimney)\n\n- #3 gamma\n")


def test_open_board_failed_fetch_markers():
    board = build_open_board(None, None)
    assert "- (failed to fetch)" in board.split("## Open PRs (wgmesh)")[0]
    assert board.count("- (failed to fetch)") == 2


# ── Sanitise gate (caller-side) ────────────────────────────────────

def test_sanitise_gate_expectation_documented():
    # Emission is caller-side; the module must carry the wall in writing:
    # every planned title/body/comment passes company/scripts/sanitise.sh
    # before publish (workflow parity).
    import wgmesh_pipeline.observation as observation
    assert "sanitise" in observation.__doc__.lower()
    assert "sanitise" in ObservationAction.__doc__.lower()
