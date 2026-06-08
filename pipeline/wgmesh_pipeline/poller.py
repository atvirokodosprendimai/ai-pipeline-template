from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue
from wgmesh_pipeline.github.reconcile import reconcile_issues
from wgmesh_pipeline.graph.nodes.gate import apply_gate_side_effects, gate_node
from wgmesh_pipeline.scoring import score_run
from wgmesh_pipeline.state.store import IssueRecord, StateStore


@dataclass
class Poller:
    config: Config
    store: StateStore
    client: GitHubClient
    graph: object
    scratch: dict[int, dict] = field(default_factory=dict)
    last_reconcile_error: str | None = None

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
            reconcile_issues(self.client, self.store)
            issue = self.store.claim_next(now=datetime.now(timezone.utc))
        except Exception as exc:
            self.last_reconcile_error = str(exc)
            return None
        if issue is None:
            return None

        started = datetime.now(timezone.utc)
        node = issue.stage
        try:
            advanced = self._advance_one_stage(issue)
        except Exception as exc:
            self.store.bump_attempt(issue.number, str(exc))
            self.store.record_run(issue=issue.number, node=node, started=started, ended=datetime.now(timezone.utc), outcome="error")
            score_run({**self.scratch.get(issue.number, {}), "issue": issue}, outcome="failed")
            return None

        self.store.record_run(issue=issue.number, node=node, started=started, ended=datetime.now(timezone.utc), outcome="ok")
        return advanced

    def _advance_one_stage(self, issue: IssueRecord) -> IssueRecord:
        graph_issue = GitHubIssue(number=issue.number, title=issue.title, labels=(), state=issue.status)
        state = {**self.scratch.get(issue.number, {}), "issue": graph_issue, "github": self.client}
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
            return self.store.transition(issue.number, "queued", "triaged")

        if issue.stage == "triaged":
            self.scratch[issue.number] = dict(self.graph.spec(state))
            return self.store.transition(issue.number, "triaged", "specced")

        if issue.stage in {"specced", "spec_ready", "implemented", "reviewed"} and self.config.mode == "shadow":
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
            return self.store.transition(issue.number, "specced", next_stage)

        if issue.stage == "spec_ready":
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
            result = gate_node(state, max_files=self.config.max_files, apply_side_effects=False)
            self.scratch[issue.number] = dict(result)
            outcome = "merged" if result["decision"] == "merge" else "escalated"
            # Side-effect BEFORE the terminal transition: if the merge/label
            # network call fails it raises here, the issue stays at 'reviewed'
            # (retried next tick, terminal-failed after max attempts), and we
            # never record a phantom-merged state with the PR unmerged. Mirrors
            # the queued branch (label before transition).
            # NOTE (follow-up): a crash in the tiny window after a *successful*
            # merge but before the transition would re-attempt the merge on
            # retry; merge_pr should tolerate an already-merged PR at the API
            # layer to make that fully idempotent.
            apply_gate_side_effects(result)
            advanced = self.store.transition(issue.number, "reviewed", outcome)
            score_run(result, outcome=outcome)
            return advanced

        raise ValueError(f"stage is not actionable: {issue.stage}")
