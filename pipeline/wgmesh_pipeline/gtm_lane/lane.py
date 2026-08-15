"""Production lane assembly (review hardening).

``execute_item`` lets each gate default to None so lower-layer tests can focus on
one concern. That flexibility is a liability in production: a single wiring slip
(verifier=None) silently degrades to dispatch-without-safety / close-without-verify.
``GtmLane`` is the production seam — it REQUIRES every gate (no defaults), so the
type system guarantees the safe path. The live queue poller constructs one
``GtmLane`` and calls ``run`` per approved item.

The provider and the verification judge are the only funding-gated pieces (they
need the funded Toloka account + the live LLM judge); everything else assembles
from config now.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from wgmesh_pipeline.gtm_lane.budget import BudgetGate
from wgmesh_pipeline.gtm_lane.executor import DraftFn, ItemOutcome, execute_item
from wgmesh_pipeline.gtm_lane.provider import HumanTaskProvider
from wgmesh_pipeline.gtm_lane.safety import SafetyGate
from wgmesh_pipeline.gtm_lane.telemetry import record_outcome
from wgmesh_pipeline.gtm_lane.verify import Verifier


@dataclass
class GtmLane:
    """All gates required — construction fails loudly if one is missing."""

    provider: HumanTaskProvider
    draft_fn: DraftFn
    safety: SafetyGate
    budget: BudgetGate
    verifier: Verifier
    telemetry_path: str | Path | None = None

    def run(self, item: Mapping[str, Any]) -> ItemOutcome:
        outcome = execute_item(
            item,
            draft_fn=self.draft_fn,
            provider=self.provider,
            safety=self.safety,
            budget=self.budget,
            verifier=self.verifier,
        )
        if self.telemetry_path is not None:
            cost = getattr(outcome.result, "cost_estimate", None)
            record_outcome(outcome.status, state_path=self.telemetry_path, cost=cost)
        return outcome
