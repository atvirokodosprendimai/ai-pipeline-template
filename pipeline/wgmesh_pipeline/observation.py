"""Box-side Observation Loop: deterministic half of the Actions workflow (cutover U3).

Port of the DETERMINISTIC parts of ``.github/workflows/observation-loop.yml``:

- input assembly — the open-issues/PRs board text fed to the LLM
  (``build_open_board``) and the open+closed title corpus the dedup guard
  reads (``build_dedup_corpus``);
- the issue-creation dedup guard — 5 lowercase keywords after the exact
  stop-word list, 2+ substring hits on a single existing title = duplicate
  (ported byte-for-byte from the shell pipeline, including the quirk that a
  leading non-alphanumeric character consumes one of the 5 keyword slots);
- the issue-close guards hardened in #1665 — needs-human label means
  human-lane only (never close), label fetch failure fails CLOSED (refuse to
  close blind), a reason that says relabel/reopen contradicts a close and is
  skipped, and every surviving close is ``not planned`` (COMPLETED is
  reserved for the merged-impl-PR closer, R5);
- the action-plan builder ``plan_actions`` — turns an LLM assessment dict
  ``{issues_to_create, issues_to_close, prs_to_close, needs_human}`` into a
  vetted action list plus a skip log.

The LLM assessment call itself stays caller-side: this module takes the
assessment as an input dict and returns planned actions — it performs ZERO
GitHub reads or writes (the label snapshot for close-vetting arrives in
``ObservationInputs.issue_labels``, gathered by the caller).

Sanitise gate (caller-side, workflow parity): every ``ObservationAction``
title/body/comment MUST pass ``company/scripts/sanitise.sh`` before the
executor publishes it — the workflow gates every ``gh issue create`` on it
and SKIPS the item when sanitisation fails. Emission, and therefore the
gate, is the caller's wall; this module only plans.

TODO(protocol gaps) — not ported in this unit (stay caller-side):
  - the LLM call + stub/error assessment fallbacks;
  - signal collection (collect-github.sh, Polar revenue, shared memory);
  - the stale needs-triage re-trigger sweep (label remove/re-add writes);
  - loop-history/state commits and the MentisDB append.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

ORG = "atvirokodosprendimai"
TARGET_REPO = f"{ORG}/wgmesh"
NEEDS_HUMAN_LABEL = "needs-human"
CLOSE_REASON_NOT_PLANNED = "not planned"
MAX_KEYWORDS = 5
DUPLICATE_MIN_HITS = 2

# Exact stop-word list from the workflow's grep -v -E '^(...)$' (both the
# issues_to_create and needs_human dedup steps use the same list).
STOP_WORDS = frozenset((
    "the", "a", "an", "in", "on", "for", "to", "of", "and", "or", "is",
    "set", "add", "configure", "verify", "check", "update", "review",
    "approve", "implement", "basic", "define", "fix", "enable",
))

# Guard 2 (#1665): the assessment's own reason contradicts a close.
_CLOSE_CONTRADICTION_RE = re.compile(r"relabel|reopen|rather than clos", re.IGNORECASE)

# tr -cs 'a-z0-9' '\n' — every run of non-[a-z0-9] squeezes to one newline.
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ObservationAction:
    """One vetted planned write. ``title``/``body``/``comment`` MUST pass the
    sanitise gate (``company/scripts/sanitise.sh``) before the executor
    publishes them — workflow parity; failing items are skipped, not fixed."""

    kind: str  # "create_issue" | "close_issue" | "create_needs_human" | "close_pr"
    repo: str = TARGET_REPO
    number: int | None = None
    title: str | None = None
    body: str | None = None
    labels: tuple[str, ...] = ()
    close_reason: str | None = None  # "not planned" for issue closes (R5); PRs carry none
    comment: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class ObservationSkip:
    """One vetoed assessment item; ``message`` mirrors the workflow's echo."""

    action: str  # the action kind that was vetoed
    code: str  # "duplicate" | "label_fetch_failed" | "needs_human_label" | "reason_contradicts_close"
    message: str
    number: int | None = None
    title: str | None = None


@dataclass(frozen=True)
class ObservationInputs:
    """Ground-truth snapshots gathered by the caller (the module never
    queries GitHub). ``issue_labels`` maps issue number -> label names; a
    MISSING number or a ``None`` value means the label fetch failed and the
    close guard fails CLOSED (#1665)."""

    open_issue_titles: tuple[str, ...] = ()
    closed_issue_titles: tuple[str, ...] = ()
    issue_labels: Mapping[int, Sequence[str] | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ObservationPlan:
    """Vetted planned actions (workflow step order: issue creates, issue
    closes, needs-human creates, PR closes) plus the skip log."""

    actions: tuple[ObservationAction, ...]
    skips: tuple[ObservationSkip, ...]


def extract_keywords(text: str) -> tuple[str, ...]:
    """Port of: tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '\\n'
    | grep -v -E '^(<stop words>)$' | head -5.

    Parity quirks kept on purpose: a leading non-alphanumeric character
    yields an empty first line which survives grep -v and CONSUMES one of
    the 5 head slots (it is later dropped by shell word-splitting — see
    ``_count_hits``); stop-word matching is exact-line, not substring.
    """
    squeezed = _NON_ALNUM_RE.sub("\n", text.lower())
    lines = squeezed.split("\n")
    if lines and lines[-1] == "":  # trailing newline is a line terminator, not an empty line
        lines.pop()
    kept = [line for line in lines if line not in STOP_WORDS]
    return tuple(kept[:MAX_KEYWORDS])


def _count_hits(keywords: Sequence[str], existing_title: str) -> int:
    """Substring hits of keywords in one lowercased existing title. Empty
    keywords are dropped here (shell word-splitting in ``for kw in
    $keywords``), NOT in ``extract_keywords`` (head -5 ran before)."""
    existing_lower = existing_title.lower()
    return sum(1 for kw in keywords if kw and kw in existing_lower)


def is_duplicate(text: str, corpus: Sequence[str]) -> bool:
    """True when any single existing title accumulates 2+ keyword hits —
    the workflow breaks on the first matching title."""
    keywords = extract_keywords(text)
    return any(_count_hits(keywords, title) >= DUPLICATE_MIN_HITS for title in corpus)


def build_dedup_corpus(inputs: ObservationInputs) -> list[str]:
    """Open titles then closed titles — the workflow appends the closed list
    after the open one (checking only open issues missed already-implemented
    features and re-created them as greenfield tasks; wgmesh#458)."""
    return list(inputs.open_issue_titles) + list(inputs.closed_issue_titles)


def build_open_board(
    primary_issues: Sequence[Mapping[str, Any]] | None,
    primary_prs: Sequence[Mapping[str, Any]] | None,
    secondary_issues: Mapping[str, Sequence[Mapping[str, Any]]] = {},
) -> str:
    """The /tmp/open_board.txt text fed to the LLM. ``None`` for a primary
    list mirrors a failed fetch (the workflow prints a failure marker rather
    than an empty section). Secondary repos appear only when non-empty."""
    lines: list[str] = ["## Open Issues (wgmesh)", ""]
    if primary_issues is None:
        lines.append("- (failed to fetch)")
    else:
        for issue in primary_issues:
            names = [str(l.get("name")) if isinstance(l, Mapping) else str(l)
                     for l in issue.get("labels") or []]
            lines.append(f"- #{issue['number']} {issue['title']} [{', '.join(names)}]")
    lines += ["", "## Open PRs (wgmesh)", ""]
    if primary_prs is None:
        lines.append("- (failed to fetch)")
    else:
        for pr in primary_prs:
            author = pr.get("author")
            login = author.get("login") if isinstance(author, Mapping) else author
            lines.append(f"- PR #{pr['number']} {pr['title']} (by {login})")
    for name, issues in secondary_issues.items():
        if not issues:
            continue
        lines += ["", f"## Open Issues ({name})", ""]
        for issue in issues:
            lines.append(f"- #{issue['number']} {issue['title']}")
    return "\n".join(lines) + "\n"


def _vet_create(item: Mapping[str, Any], corpus: list[str], *, kind: str,
                title: str, body: str, labels: tuple[str, ...],
                skip_message: str) -> tuple[ObservationAction | None, ObservationSkip | None]:
    """Shared dedup gate for both create steps. On create the title joins the
    corpus so later items in the SAME run dedup against it (workflow appends
    to /tmp/open_issues.txt)."""
    dedup_text = str(item.get("request") or item.get("title") or "")
    if is_duplicate(dedup_text, corpus):
        return None, ObservationSkip(action=kind, code="duplicate",
                                     message=skip_message, title=title)
    corpus.append(title)
    return ObservationAction(kind=kind, title=title, body=body, labels=labels), None


def vet_issue_close(item: Mapping[str, Any],
                    issue_labels: Mapping[int, Sequence[str] | None],
                    ) -> tuple[ObservationAction | None, ObservationSkip | None]:
    """The #1665 close-guard chain, in workflow order. A malformed/missing
    number lands in the fail-closed branch too: the workflow's ``gh issue
    view "null"`` fails the label fetch, which refuses the close."""
    reason = str(item.get("reason") or "")
    try:
        number = int(item["number"])
    except (KeyError, TypeError, ValueError):
        return None, ObservationSkip(
            action="close_issue", code="label_fetch_failed",
            message=f"SKIP close #{item.get('number')}: label fetch failed — "
                    f"refusing to close blind (reason was: {reason})")
    # Guard 1 (fail-closed): no label snapshot -> refuse to close blind.
    labels = issue_labels.get(number)
    if labels is None:
        return None, ObservationSkip(
            action="close_issue", code="label_fetch_failed", number=number,
            message=f"SKIP close #{number}: label fetch failed — "
                    f"refusing to close blind (reason was: {reason})")
    # Guard 1: never autonomously close a human escalation (closed #652 once).
    joined = ",".join(str(l) for l in labels)
    if f",{NEEDS_HUMAN_LABEL}," in f",{joined},":
        return None, ObservationSkip(
            action="close_issue", code="needs_human_label", number=number,
            message=f"SKIP close #{number}: needs-human label — human-lane only "
                    f"(reason was: {reason})")
    # Guard 2: the assessment's own reason says relabel/reopen -> not a close.
    if _CLOSE_CONTRADICTION_RE.search(reason):
        return None, ObservationSkip(
            action="close_issue", code="reason_contradicts_close", number=number,
            message=f"SKIP close #{number}: reason contradicts close action: {reason}")
    # Guard 3 (R5): an LLM assessment is a non-merge signal — close as
    # 'not planned', never COMPLETED.
    return ObservationAction(
        kind="close_issue", number=number, close_reason=CLOSE_REASON_NOT_PLANNED,
        comment=f"Closed by observation loop: {reason}", reason=reason), None


def plan_actions(assessment: Mapping[str, Any], inputs: ObservationInputs) -> ObservationPlan:
    """Turn an LLM assessment dict into vetted planned actions + a skip log.

    Mirrors the workflow's act steps in order. Missing assessment keys are
    empty lists (jq ``// []``). No writes happen here — the caller executes
    actions behind the sanitise gate.
    """
    actions: list[ObservationAction] = []
    skips: list[ObservationSkip] = []
    corpus = build_dedup_corpus(inputs)

    for item in assessment.get("issues_to_create") or []:
        title = str(item.get("title") or "")
        if not title:
            raise ValueError(f"issues_to_create entry without a title: {item!r}")
        raw_labels = item.get("labels") or []
        action, skip = _vet_create(
            item, corpus, kind="create_issue", title=title,
            body=str(item.get("body") or ""),
            labels=tuple(str(l) for l in raw_labels),
            skip_message=f"Skipping duplicate: {title}")
        if action:
            actions.append(action)
        if skip:
            skips.append(skip)

    for item in assessment.get("issues_to_close") or []:
        action, skip = vet_issue_close(item, inputs.issue_labels)
        if action:
            actions.append(action)
        if skip:
            skips.append(skip)

    for req in assessment.get("needs_human") or []:
        request = str(req.get("request") or "")
        if not request:
            raise ValueError(f"needs_human entry without a request: {req!r}")
        full_title = f"[{NEEDS_HUMAN_LABEL}] {request}"
        body = (f"**Urgency**: {req.get('urgency')}\n\n"
                f"**Reason**: {req.get('reason')}\n\n_Created by observation loop._")
        action, skip = _vet_create(
            req, corpus, kind="create_needs_human", title=full_title, body=body,
            labels=(NEEDS_HUMAN_LABEL,),
            skip_message=f"Skipping duplicate needs-human: {request}")
        if action:
            actions.append(action)
        if skip:
            skips.append(skip)

    for item in assessment.get("prs_to_close") or []:
        # Workflow parity: PR closes carry no guards and no close reason —
        # just the comment. Repo arrives as the short name.
        reason = str(item.get("reason") or "")
        actions.append(ObservationAction(
            kind="close_pr", repo=f"{ORG}/{item['repo']}", number=int(item["number"]),
            comment=f"Closed by observation loop: {reason}", reason=reason))

    return ObservationPlan(actions=tuple(actions), skips=tuple(skips))
