from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from wgmesh_pipeline.config import Config
from wgmesh_pipeline.github.client import GitHubClient, GitHubIssue
from wgmesh_pipeline.github.reconcile import reconcile_issues
from wgmesh_pipeline.graph.nodes.gate import gate_node
from wgmesh_pipeline.state.store import IssueRecord, StateStore


@dataclass
class Poller:
    config: Config
    store: StateStore
    client: GitHubClient
    graph: object
    scratch: dict[int, dict] = field(default_factory=dict)

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.config.poll_interval_seconds)
            except TimeoutError:
                continue

    async def tick(self) -> IssueRecord | None:
        reconcile_issues(self.client, self.store)
        issue = self.store.claim_next(now=datetime.now(timezone.utc))
        if issue is None:
            return None

        started = datetime.now(timezone.utc)
        node = issue.stage
        try:
            advanced = self._advance_one_stage(issue)
        except Exception as exc:
            self.store.bump_attempt(issue.number, str(exc))
            self.store.record_run(issue=issue.number, node=node, started=started, ended=datetime.now(timezone.utc), outcome="error")
            return None

        self.store.record_run(issue=issue.number, node=node, started=started, ended=datetime.now(timezone.utc), outcome="ok")
        return advanced

    def _advance_one_stage(self, issue: IssueRecord) -> IssueRecord:
        graph_issue = GitHubIssue(number=issue.number, title=issue.title, labels=(), state=issue.status)
        state = {**self.scratch.get(issue.number, {}), "issue": graph_issue, "github": self.client}

        if issue.stage == "queued":
            result = self.graph.triage(state)
            self.scratch[issue.number] = dict(result)
            classification = result.get("classification")
            if classification in {"wont-do", "needs-info"}:
                self.client.add_label(issue.number, "needs-human")
                return self.store.transition(issue.number, "queued", "escalated")
            self.store.upsert_issue(issue.number, issue.title, classification=classification, stage="queued")
            return self.store.transition(issue.number, "queued", "triaged")

        if issue.stage == "triaged":
            self.scratch[issue.number] = dict(self.graph.spec(state))
            return self.store.transition(issue.number, "triaged", "specced")

        if issue.stage == "specced":
            self.scratch[issue.number] = dict(self.graph.implement(state))
            return self.store.transition(issue.number, "specced", "implemented")

        if issue.stage == "implemented":
            self.scratch[issue.number] = dict(self.graph.review(state))
            return self.store.transition(issue.number, "implemented", "reviewed")

        if issue.stage == "reviewed":
            result = gate_node(state, max_files=self.config.max_files)
            self.scratch[issue.number] = dict(result)
            return self.store.transition(issue.number, "reviewed", "merged" if result["decision"] == "merge" else "escalated")

        raise ValueError(f"stage is not actionable: {issue.stage}")
