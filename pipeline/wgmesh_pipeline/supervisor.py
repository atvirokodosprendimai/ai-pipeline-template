"""Box-side Supervisor-Rank: clog classification, ranking, and state building.

Port of the Actions ``supervisor-rank`` workflow (cutover plan U5): the
``classify-clogs.sh`` → ``rank-clogs.sh`` → ``recommend-actions.sh`` chain
collapses into the pure function ``rank_clogs``; the state half of
``publish-rank.sh`` (top-3 delta, run counter, material fingerprint) becomes
``build_state``. Semantics are ported, not redesigned — dwell x
downstream-blocked scoring, taxonomy stage rules, jq sort order, and the
sha256 fingerprint are byte/ordering-compatible with the Actions ranker
(parity-tested against the recorded ``company/supervisor-rank-state.json``).

Read-only surface: recommends, does not act. ``build_state`` RETURNS the
state dict; persisting it and publishing the anchor issue (#934) stay with
the caller.

TODO(protocol gaps) — the Forge protocol cannot yet feed a full snapshot, so
``run_supervisor_rank`` accepts plain-dict snapshot items gathered elsewhere.
Missing methods (do NOT extend the protocol in this unit):
  - ``Forge.list_open_prs()`` returning review_decision, merge_state_status,
    is_draft, created_at, updated_at — needed for PR clogs + merge stage.
  - ``ForgeIssue`` lacks created_at / updated_at / url — needed for
    dwell_hours; forge-sourced issues therefore classify with dwell 0.
  - No cross-repo listing — TARGET_REPOS spans two repos, a Forge instance
    is bound to one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from wgmesh_pipeline.forge.protocol import Forge

STAGE_ORDER: tuple[str, ...] = (
    "triage", "spec", "build", "review", "merge", "verify", "revenue", "unknown",
)

# Taxonomy match order after the hard-coded overrides (mirrors jq stage()).
_MATCH_ORDER: tuple[str, ...] = ("revenue", "verify", "review", "build", "spec", "triage")

DEFAULT_TOP_N = 5


@dataclass(frozen=True)
class RankedClog:
    """One ranked item, mirroring the fields ``rank-clogs.sh`` emits per entry."""

    rank: int
    id: str
    repo: str
    type: str
    number: int
    title: str
    stage: str
    dwell_hours: int
    downstream_blocked_count: int
    score: int
    recommended_action: str | None  # None when stage has no allowlisted action


@dataclass(frozen=True)
class RankResult:
    """Ranked output, mirroring the shape of ``/tmp/ranked.json`` in Actions."""

    generated_at: str
    top: tuple[RankedClog, ...]
    stage_summary: Mapping[str, int]
    unknown: tuple[Mapping[str, Any], ...]

    @property
    def top_ids(self) -> list[str]:
        """Top-3 ids — the rank-change fingerprint unit in publish-rank.sh."""
        return [clog.id for clog in self.top[:3]]

    @property
    def top_actions(self) -> list[dict[str, Any]]:
        """Top-5 ``{id, action}`` pairs as recorded in the state file."""
        return [{"id": c.id, "action": c.recommended_action} for c in self.top[:DEFAULT_TOP_N]]


@dataclass(frozen=True)
class SupervisorInputs:
    """Inputs to ``rank_clogs``. ``items`` use the snapshot-clogs.sh dict shape:
    repo, type ("pr"|"issue"), number, title, labels (names or ``{"name":…}``),
    created_at, updated_at, is_draft, review_decision, merge_state_status, url."""

    items: tuple[Mapping[str, Any], ...]
    taxonomy: Mapping[str, Any]
    now: str
    top_n: int = DEFAULT_TOP_N


@dataclass(frozen=True)
class SupervisorRankRun:
    """Runner outcome: ranked result + the state dict the caller may persist.
    ``material_changed`` is the commit-gate sentinel from publish-rank.sh: when
    False the caller must NOT persist ``state`` (anti PR-per-run pile-up)."""

    result: RankResult
    state: dict[str, Any]
    material_changed: bool
    rank_changed: bool = False


def load_taxonomy(path: str | Path) -> dict[str, Any]:
    """Load and validate ``company/pipeline-stages.json`` (classify-clogs.sh guard)."""
    taxonomy = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(taxonomy.get("stages"), list):
        raise ValueError(f"bad taxonomy {path}: stages must be an array")
    rules = taxonomy.get("classification_rules")
    if not isinstance(rules, dict):
        raise ValueError(f"bad taxonomy {path}: classification_rules must be an object")
    for stage in taxonomy["stages"]:
        if not isinstance(rules.get(stage), dict):
            raise ValueError(f"bad taxonomy {path}: missing classification rule for {stage}")
    if not isinstance(taxonomy.get("recommended_actions"), dict):
        raise ValueError(f"bad taxonomy {path}: recommended_actions must be an object")
    return taxonomy


def _label_names(item: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for label in item.get("labels") or []:
        if isinstance(label, Mapping):
            name = label.get("name")
            if name is not None:
                names.append(str(name))
        elif label is not None:
            names.append(str(label))
    return names


def _has_label(item: Mapping[str, Any], name: str) -> bool:
    return name in _label_names(item)


def _title_starts(item: Mapping[str, Any], prefixes: Sequence[str]) -> bool:
    title = str(item.get("title") or "").lower()
    return any(title.startswith(str(prefix).lower()) for prefix in prefixes)


def _matches(item: Mapping[str, Any], stage: str, taxonomy: Mapping[str, Any]) -> bool:
    rule: Mapping[str, Any] = (taxonomy.get("classification_rules") or {}).get(stage) or {}
    if any(_has_label(item, name) for name in rule.get("label_any") or []):
        return True
    if _title_starts(item, rule.get("title_prefix_any") or []):
        return True
    decisions = rule.get("review_decision_any") or []
    if decisions and str(item.get("review_decision") or "") in decisions:
        statuses = rule.get("merge_state_status_any") or []
        if not statuses or str(item.get("merge_state_status") or "") in statuses:
            return True
    if (
        stage == "triage"
        and item.get("type") == "issue"
        and rule.get("issue_without_type_label", False) is True
    ):
        names = _label_names(item)
        if not any(name.startswith("type:") for name in names) and len(names) == 0:
            return True
    return False


def classify_stage(item: Mapping[str, Any], taxonomy: Mapping[str, Any]) -> str:
    """Stage for one item — exact port of jq ``stage()`` in classify-clogs.sh."""
    if _has_label(item, "needs-human"):
        return "review"
    if str(item.get("title") or "").lower().startswith("spec:"):
        return "spec"
    if (
        item.get("type") == "pr"
        and str(item.get("review_decision") or "") == "APPROVED"
        and str(item.get("merge_state_status") or "") in ("CLEAN", "HAS_HOOKS")
    ):
        return "merge"
    for stage in _MATCH_ORDER:
        if _matches(item, stage, taxonomy):
            return stage
    return "unknown"


def _first_present(item: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return None


def _parse_iso8601(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _dwell_hours(item: Mapping[str, Any], stage: str, now: str) -> int:
    if stage == "triage" and _has_label(item, "copilot-triaging"):
        start = _first_present(item, ("updated_at", "updatedAt", "created_at", "createdAt"))
    else:
        start = _first_present(item, ("created_at", "createdAt", "updated_at", "updatedAt"))
    if not start:
        return 0
    delta = (_parse_iso8601(now) - _parse_iso8601(start)).total_seconds() / 3600
    return max(int(delta // 1), 0)  # jq floor, clamped at 0


def classify_items(
    items: Sequence[Mapping[str, Any]], taxonomy: Mapping[str, Any], now: str
) -> list[dict[str, Any]]:
    """Annotate snapshot items with ``stage`` + ``dwell_hours`` (new dicts)."""
    classified: list[dict[str, Any]] = []
    for item in items:
        stage = classify_stage(item, taxonomy)
        classified.append({**item, "stage": stage, "dwell_hours": _dwell_hours(item, stage, now)})
    return classified


def _blocked_count(item: Mapping[str, Any], items: Sequence[Mapping[str, Any]]) -> int:
    """Downstream-blocked multiplier — exact port of rank-clogs.sh."""
    stage = item.get("stage") or "unknown"
    repo = item.get("repo")

    def count(stages: tuple[str, ...]) -> int:
        n = sum(1 for it in items if it.get("repo") == repo and (it.get("stage") or "") in stages)
        return max(n, 1)

    if stage == "spec":
        return count(("build",))
    if stage == "triage":
        return count(("spec", "build", "review"))
    if stage == "merge":
        return count(("merge",))
    if stage == "unknown":
        return 0
    return 1


def _recommended_action(stage: str, taxonomy: Mapping[str, Any]) -> str | None:
    """Action for a stage — port of recommend-actions.sh (allowlist-gated)."""
    action = (taxonomy.get("recommended_actions") or {}).get(stage)
    if action is not None and action in (taxonomy.get("allowed_actions") or []):
        return str(action)
    return None


def rank_clogs(inputs: SupervisorInputs) -> RankResult:
    """Classify, score, and rank clogs — port of the Actions ranker chain.

    score = dwell_hours x downstream_blocked_count; top-N excludes unknown,
    sorted by (-score, created_at, repo, number); stage_summary spans all
    items; unknown listed separately sorted by (repo, number).
    """
    classified = classify_items(inputs.items, inputs.taxonomy, inputs.now)

    scored: list[dict[str, Any]] = []
    for item in classified:
        blocked = _blocked_count(item, classified)
        scored.append({
            **item,
            "id": f"{item.get('repo')}#{item.get('number')}",
            "downstream_blocked_count": blocked,
            "score": (item.get("dwell_hours") or 0) * blocked,
        })

    rankable = [it for it in scored if (it.get("stage") or "unknown") != "unknown"]
    rankable.sort(key=lambda it: (
        -(it.get("score") or 0),
        _first_present(it, ("created_at", "createdAt")) or "",
        it.get("repo") or "",
        it.get("number") or 0,
    ))

    top = tuple(
        RankedClog(
            rank=position + 1,
            id=it["id"],
            repo=it.get("repo") or "",
            type=it.get("type") or "",
            number=int(it.get("number") or 0),
            title=it.get("title") or "",
            stage=it["stage"],
            dwell_hours=int(it.get("dwell_hours") or 0),
            downstream_blocked_count=int(it["downstream_blocked_count"]),
            score=int(it["score"]),
            recommended_action=_recommended_action(it["stage"], inputs.taxonomy),
        )
        for position, it in enumerate(rankable[: inputs.top_n])
    )

    stage_summary = {
        stage: sum(1 for it in classified if (it.get("stage") or "unknown") == stage)
        for stage in STAGE_ORDER
    }

    unknown = sorted(
        (
            {key: it.get(key) for key in ("id", "repo", "type", "number", "title", "stage")}
            for it in scored
            if (it.get("stage") or "unknown") == "unknown"
        ),
        key=lambda it: (it.get("repo") or "", it.get("number") or 0),
    )

    return RankResult(
        generated_at=inputs.now, top=top, stage_summary=stage_summary, unknown=tuple(unknown)
    )


def material_fingerprint(result: RankResult) -> str:
    """sha256 over the material fields — byte-compatible with publish-rank.sh.
    The shell uses ``jq -Sc`` (recursively sorted keys, compact separators);
    ``json.dumps(sort_keys=True, separators=(",", ":"))`` produces identical
    bytes, verified against the recorded fingerprint on main."""
    payload = {
        "top_ids": result.top_ids,
        "stage_summary": dict(result.stage_summary),
        "unknown_count": len(result.unknown),
        "top_actions": result.top_actions,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_state(
    result: RankResult, previous_state: Mapping[str, Any] | None = None
) -> SupervisorRankRun:
    """Build the supervisor-rank state dict — port of publish-rank.sh state logic.
    Returns the would-be ``company/supervisor-rank-state.json`` content plus the
    ``material_changed`` sentinel: ``rank_changed`` compares top-3 ids against
    the prior run (empty prior never flags), ``run_number`` increments, and
    ``issue_number``/``issue_url`` carry over (publishing is the caller's job)."""
    prev = previous_state or {}
    previous_top = list(prev.get("last_run_top_ids") or [])
    previous_fingerprint = str(prev.get("material_fingerprint") or "")
    current_top = result.top_ids
    rank_changed = bool(previous_top) and previous_top != current_top
    fingerprint = material_fingerprint(result)
    material_changed = not (previous_fingerprint and previous_fingerprint == fingerprint)
    state: dict[str, Any] = {
        "last_run_at": result.generated_at,
        "last_run_top_ids": current_top,
        "rank_changed": rank_changed,
        "run_number": int(prev.get("run_number") or 0) + 1,
        "issue_number": prev.get("issue_number"),
        "issue_url": prev.get("issue_url"),
        "stage_summary": dict(result.stage_summary),
        "unknown_count": len(result.unknown),
        "top_actions": result.top_actions,
        "material_fingerprint": fingerprint,
    }
    return SupervisorRankRun(
        result=result, state=state, material_changed=material_changed, rank_changed=rank_changed
    )


def snapshot_from_forge(forge: Forge, repo: str) -> list[dict[str, Any]]:
    """Best-effort snapshot via existing Forge methods only.
    Degraded relative to snapshot-clogs.sh (see protocol gaps at module top):
    no timestamps (dwell 0), no review_decision / merge_state_status (no
    merge-stage detection), single repo. Items whose ``pull_request`` payload
    is present become ``type: "pr"`` (GitHub /issues returns PRs too)."""
    return [
        {
            "repo": repo,
            "type": "pr" if issue.pull_request else "issue",
            "number": issue.number,
            "title": issue.title,
            "labels": list(issue.labels),
            "created_at": None,
            "updated_at": None,
            "is_draft": False,
            "url": None,
        }
        for issue in forge.list_open_issues()
    ]


def run_supervisor_rank(
    forge: Forge,
    *,
    taxonomy: Mapping[str, Any],
    repo: str,
    previous_state: Mapping[str, Any] | None = None,
    snapshot: Sequence[Mapping[str, Any]] | None = None,
    now: str | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> SupervisorRankRun:
    """Gather inputs, rank, and return the state dict. No forge writes.
    ``snapshot`` (plain dicts, snapshot-clogs.sh shape) overrides the degraded
    forge-derived snapshot until the protocol grows the listed gap methods.
    Persisting the returned ``state`` (only when ``material_changed``) and
    publishing the anchor issue remain the caller's responsibility."""
    items = list(snapshot) if snapshot is not None else snapshot_from_forge(forge, repo)
    timestamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inputs = SupervisorInputs(items=tuple(items), taxonomy=taxonomy, now=timestamp, top_n=top_n)
    return build_state(rank_clogs(inputs), previous_state)
