from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.forge.protocol import Forge, ForgeIssue as GitHubIssue
from wgmesh_pipeline.forge.quackback_status import is_active_lane, status_for_stage
from wgmesh_pipeline.github.reconcile import reconcile_issues, reconcile_quackback
from wgmesh_pipeline.graph.nodes.gate import apply_gate_side_effects, gate_node
from wgmesh_pipeline.graph.nodes.guards import guards_node
from wgmesh_pipeline.scoring import score_run
from wgmesh_pipeline.state.store import ACTIONABLE_STAGES, IssueRecord, StateStore

log = logging.getLogger("wgmesh_pipeline.poller")


@dataclass
class Poller:
    config: Config
    store: StateStore
    client: Forge
    graph: object
    resolution_lookup: object | None = None
    goose_runner: object | None = None
    scratch: dict[int, dict] = field(default_factory=dict)
    last_reconcile_error: str | None = None

    def __post_init__(self) -> None:
        # U6: wire the store-backed post-id resolver so the Quackback forge can
        # resolve ids for posts ingested via the store mapping (which never
        # populated the forge's in-memory _id_map). Best-effort + duck-typed: a
        # github forge has no bind_resolver and is skipped.
        if getattr(self.config, "forge_kind", "github") == "quackback":
            binder = getattr(self.client, "bind_resolver", None)
            if callable(binder):
                binder(self.store.quackback_post_id_for)

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.config.poll_interval_seconds)
            except TimeoutError:
                continue

    async def tick(self) -> IssueRecord | None:
        try:
            if getattr(self.config, "forge_kind", "github") == "quackback":
                # Quackback posts have no GitHub-label semantics — the dedicated
                # ingest upserts only 'Accepted for Build' posts at queued (KTD3).
                result = reconcile_quackback(self.client, self.store)
            else:
                result = reconcile_issues(self.client, self.store, resolution_lookup=self.resolution_lookup)
            claim_stages = ACTIONABLE_STAGES
            if self.config.mode != "spec-only":
                claim_stages = ACTIONABLE_STAGES + ("spec_opened",)
            issue = self.store.claim_next(now=datetime.now(timezone.utc), stages=claim_stages)
        except Exception as exc:
            # Never silently swallow: a reconcile/claim failure here previously
            # left the loop reconciling-but-never-advancing with the cause
            # hidden in last_reconcile_error. Surface it loudly every tick.
            self.last_reconcile_error = str(exc)
            score_run(_failure_score_state("reconcile", exc), outcome="failed")
            log.exception("tick: reconcile/claim failed: %s", exc)
            return None
        log.info(
            "tick: reconcile seen=%s queued=%s; claimed=%s",
            getattr(result, "seen", "?"), getattr(result, "queued", "?"),
            f"#{issue.number}@{issue.stage}" if issue else "none",
        )
        if issue is None:
            return None

        started = datetime.now(timezone.utc)
        node = issue.stage
        try:
            advanced = self._advance_one_stage(issue)
        except Exception as exc:
            self.store.bump_attempt(issue.number, str(exc))
            self.store.record_run(issue=issue.number, node=node, started=started, ended=datetime.now(timezone.utc), outcome="error")
            score_run({**self.scratch.get(issue.number, {}), **_failure_score_state(node, exc), "issue": issue}, outcome="failed")
            log.exception("tick: advance #%s@%s failed: %s", issue.number, node, exc)
            return None

        self.store.record_run(issue=issue.number, node=node, started=started, ended=datetime.now(timezone.utc), outcome="ok")
        log.info("tick: advanced #%s %s -> %s", issue.number, node, getattr(advanced, "stage", "?"))
        return advanced

    def _advance_one_stage(self, issue: IssueRecord) -> IssueRecord:
        graph_issue = GitHubIssue(number=issue.number, title=issue.title, labels=(), state=issue.status)
        state = {
            **self.scratch.get(issue.number, {}),
            "issue": graph_issue,
            "github": self.client,
            "config": self.config,
            "repo_path": Path(self.config.repo_path),
        }
        if self.goose_runner is not None:
            state["goose_runner"] = self.goose_runner
        if issue.impl_pr is not None:
            state["impl_pr"] = issue.impl_pr
        if issue.spec_pr is not None:
            state["spec_pr"] = issue.spec_pr
        if issue.stage in {"specced", "spec_ready"}:
            state.setdefault("spec_path", f"specs/issue-{issue.number}-spec.md")

        if issue.stage == "queued":
            result = self.graph.triage(state)
            self.scratch[issue.number] = dict(result)
            classification = result.get("classification")
            if classification in {"wont-do", "needs-info"}:
                self.client.add_label(issue.number, "needs-human")
                advanced = self.store.transition(issue.number, "queued", "escalated")
                score_run(result, outcome="escalated")
                return advanced
            self.store.upsert_issue(issue.number, issue.title, classification=classification, stage="queued")
            advanced = self.store.transition(issue.number, "queued", "triaged")
            # U12 drift check at first real claim + Building flip: if the founder
            # has moved the post out of the lane since accept, the mirror helper
            # escalates the store row and we return that escalated record instead
            # of doing spec/PR work.
            if not self._mirror_quackback(issue.number, "triaged"):
                return self.store.get_issue(issue.number)
            return advanced

        if issue.stage == "triaged":
            self.scratch[issue.number] = dict(self.graph.spec(state))
            return self.store.transition(issue.number, "triaged", "specced")

        if issue.stage in {"specced", "spec_ready", "implemented", "reviewed", "awaiting_merge"} and self.config.mode == "shadow":
            return issue

        if issue.stage == "specced":
            self.scratch[issue.number] = dict(self.graph.spec_pr(state))
            if self.scratch[issue.number].get("spec_pr") is not None:
                self.store.upsert_issue(
                    issue.number,
                    issue.title,
                    classification=issue.classification,
                    stage="specced",
                    status=issue.status,
                    spec_pr=int(self.scratch[issue.number]["spec_pr"]),
                )
            next_stage = "spec_opened" if self.config.mode == "spec-only" else "spec_ready"
            advanced = self.store.transition(issue.number, "specced", next_stage)
            # spec_opened is the spec-only terminal — score it so the Langfuse
            # Scores view reflects spec-only throughput (the happy path otherwise
            # emits no score; scoring only fired on escalate/error/merge).
            if next_stage == "spec_opened":
                score_run(self.scratch[issue.number], outcome="spec_opened")
            return advanced

        if issue.stage == "spec_opened":
            # spec-only terminal; in live mode the spec PR is already open, so the
            # issue resumes at implementation.
            return self.store.transition(issue.number, "spec_opened", "spec_ready")

        if issue.stage == "spec_ready":
            # U12 drift check BEFORE the impl PR is opened: if the founder moved
            # the post out of the lane, abort here so no PR is opened against a
            # cancelled/refined decision. (Building is already mirrored from the
            # triaged claim; the helper re-reads and only escalates on drift.)
            if not self._mirror_quackback(issue.number, "spec_ready"):
                return self.store.get_issue(issue.number)
            self.scratch[issue.number] = dict(self.graph.implement(state))
            if self.scratch[issue.number].get("impl_pr") is not None:
                self.store.upsert_issue(
                    issue.number,
                    issue.title,
                    classification=issue.classification,
                    stage="spec_ready",
                    status=issue.status,
                    impl_pr=int(self.scratch[issue.number]["impl_pr"]),
                )
            return self.store.transition(issue.number, "spec_ready", "implemented")

        if issue.stage == "implemented":
            self.scratch[issue.number] = dict(self.graph.review(state))
            return self.store.transition(issue.number, "implemented", "reviewed")

        if issue.stage == "reviewed":
            # #1599 Phase D: run the bot-PR leak guards (PII + emit-sanitise that
            # the standalone Actions workflows skip for bot/* heads) and post the
            # shared ci/guards required status BEFORE the gate decides, so the
            # gate sees pii_ok/emit_sanitise_ok and GitHub auto-merge has the
            # required check to wait on. Fail-closed inside guards_node.
            state = guards_node(state)
            result = gate_node(state, max_files=self.config.max_files, apply_side_effects=False)
            # Side-effect BEFORE the terminal transition: if the merge/label
            # network call fails it raises here, the issue stays at 'reviewed'
            # (retried next tick, terminal-failed after max attempts), and we
            # never record a phantom-merged state with the PR unmerged. Mirrors
            # the queued branch (label before transition).
            # NOTE (follow-up): a crash in the tiny window after a *successful*
            # merge but before the transition would re-attempt the merge on
            # retry; merge_pr should tolerate an already-merged PR at the API
            # layer to make that fully idempotent.
            # U4 judge-gated automerge: on a merge decision the side effect only
            # ENABLES GitHub auto-merge; the box does not merge. The issue parks
            # in awaiting_merge and is completed to terminal merged only once the
            # PR has actually merged (the awaiting_merge handler below) — never
            # here. This preserves the cardinal invariant: no merged state while
            # the PR is still open.
            apply_gate_side_effects(result)
            self.scratch[issue.number] = dict(result)
            outcome = "awaiting_merge" if result["decision"] == "merge" else "escalated"
            advanced = self.store.transition(issue.number, "reviewed", outcome)
            score_run(result, outcome=outcome)
            # U6 review milestone: mirror to "Ready for Review" once the gate
            # decides to merge (auto-merge enabled, PR parked). Drift-guarded: a
            # post moved out of the lane escalates instead. Only on the merge
            # path — an escalated review is a box-internal halt, not a review
            # milestone for the founder's board.
            if outcome == "awaiting_merge" and not self._mirror_quackback(
                issue.number, "reviewed"
            ):
                return self.store.get_issue(issue.number)
            return advanced

        if issue.stage == "awaiting_merge":
            # Terminal outcomes are scored HERE (not at reviewed->awaiting_merge,
            # which only records the intermediate 'awaiting_merge' state): the
            # auto_merged signal must reflect a REAL merge, never an enabled-but-
            # pending one. Carry the original run's tags from scratch so the
            # merged/escalated score keeps model/risk/escalation attribution.
            score_state = {**self.scratch.get(issue.number, {}), "issue": issue}
            impl_pr = issue.impl_pr
            if impl_pr is None:
                self.client.add_label(issue.number, "needs-human")
                score_run(score_state, outcome="escalated")
                return self.store.transition(issue.number, "awaiting_merge", "escalated")
            pr = self.client.get_pr(int(impl_pr))
            if bool(pr.get("merged") or pr.get("merged_at")):
                # Real merge confirmed -> terminal. (The seed repo's
                # impl-merged-close workflow closes the issue on the merge.)
                # U6 Shipped flip: ONLY on a real merge (this branch, gated by
                # pr.merged) AND only if the post is still in the box's lane (the
                # drift re-read inside the helper). The mirror to "Shipped" fires
                # via status_for_stage("merged").
                in_lane = self._mirror_quackback(issue.number, "merged")
                score_run(score_state, outcome="merged")
                if not in_lane:
                    # Post drifted out of the lane at merge time. The GitHub merge
                    # already happened (an irreversible fact, so it is scored),
                    # but the human moved the post out of the box's lane — the
                    # helper has set the store row to 'escalated'; do NOT flip to
                    # Shipped and do NOT force a merged transition over the human
                    # decision.
                    return self.store.get_issue(issue.number)
                return self.store.transition(issue.number, "awaiting_merge", "merged")
            if str(pr.get("state") or "") == "closed":
                # Closed without merging — judge/checks failed or a human closed it.
                self.client.add_label(issue.number, "needs-human")
                score_run(score_state, outcome="escalated")
                return self.store.transition(issue.number, "awaiting_merge", "escalated")
            # Still open: auto-merge fires when impl-judge + build + status pass.
            # Refresh updated_at so other work is claimed fairly, then re-poll on
            # a later tick. No transition — never record merged while the PR is
            # open (no phantom completion).
            self.store.upsert_issue(
                issue.number,
                issue.title,
                classification=issue.classification,
                stage="awaiting_merge",
                status=issue.status,
                spec_pr=issue.spec_pr,
                impl_pr=issue.impl_pr,
            )
            return issue

        raise ValueError(f"stage is not actionable: {issue.stage}")

    def _mirror_quackback(self, number: int, stage: str) -> bool:
        """Mirror the box's execution milestone to the Quackback post + guard drift.

        Returns ``True`` when work should CONTINUE, ``False`` when the post
        drifted out of the box's lane and work was aborted (U12).

        Everything here is best-effort and never raises into the tick loop:

          - **non-Quackback forge** → no-op, return ``True``.
          - **drift re-read (U12):** read the post's decision status. A *clear*
            out-of-lane read (Cancelled / Needs Refinement / Rejected / Open for
            Vote) means the founder moved it out of the lane — log a warning,
            defensively transition the store row to ``escalated`` (so the box
            stops working it), and return ``False``. The human decision is NEVER
            overwritten (no ``set_status``).
          - **mirror:** otherwise flip the post to the status the stage maps to
            (``status_for_stage``). A mirror-write failure is logged and
            swallowed — a telemetry-style status write must never block the
            execution path (telemetry-write lesson).

        Read-error policy (documented choice): if the drift re-read itself errors
        (network/parse), the box does NOT falsely abort — it logs and returns
        ``True``. A mirror-time read failure should not strand in-flight work;
        the fail-closed *Accepted* gate lives in the ingest read elsewhere
        (``list_accepted_posts``). Only a CLEAR out-of-lane status aborts.
        """
        if getattr(self.config, "forge_kind", "github") != "quackback":
            return True

        try:
            status = self.client.get_decision_status(number)
        except Exception as exc:
            # Non-fatal: a mirror-time read error must not strand work.
            log.warning(
                "quackback mirror: get_decision_status(#%s) failed, continuing: %s",
                number,
                exc,
            )
            return True

        if not is_active_lane(status):
            # Founder moved the post out of the box's lane — abort, never
            # overwrite the human decision.
            log.warning(
                "quackback drift: #%s left the box lane (status=%r); aborting "
                "and escalating",
                number,
                status,
            )
            try:
                self.store.set_stage(number, "escalated")
            except Exception as exc:
                log.warning(
                    "quackback drift: failed to escalate #%s in store: %s",
                    number,
                    exc,
                )
            return False

        target = status_for_stage(stage)
        if target is not None:
            try:
                self.client.set_status(number, target)
            except Exception as exc:
                # A status-mirror error must not block the execution path.
                log.warning(
                    "quackback mirror: set_status(#%s, %r) failed: %s",
                    number,
                    target,
                    exc,
                )
        return True


def _failure_score_state(node: str, exc: BaseException) -> dict:
    error = str(exc)[:200]
    return {"node": node, "stage": node, "error": error}
