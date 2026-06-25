"""Job-class safety gate (U4).

Two guards before a job is dispatched to a rented human:
  1. The job class must be in the low-risk allowlist (job_spec.LOW_RISK_CLASSES) —
     anything else, especially outbound-as-the-company, is rejected to needs-human.
  2. The outbound job-spec text passes the sanitise wall (company/scripts/sanitise.sh),
     which fails-closed on secrets and uses narrow patterns (the bare word "key" is
     not flagged). The same sanitiser is reused on the inbound returned artifact (U5).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from wgmesh_pipeline.gtm_lane.job_spec import LOW_RISK_CLASSES, JobSpec


class SafetyRejection(Exception):
    """Raised when a job spec fails the safety gate (escalate to needs-human)."""


def run_sanitise(text: str, *, script: str | Path) -> bool:
    """Run the sanitise wall over ``text``. Returns True when clean, False when a
    secret was detected (the script exits non-zero). Fail-closed: a script error
    is treated as not-clean."""
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


# Sanitiser callable: text -> True when clean. Injectable for tests.
Sanitiser = Callable[[str], bool]


@dataclass
class SafetyGate:
    sanitiser: Sanitiser

    def check(self, job_spec: JobSpec) -> None:
        """Raise SafetyRejection if the job is not a low-risk class or its spec
        text carries a secret. No return value — passing means safe to dispatch."""
        if job_spec.job_class not in LOW_RISK_CLASSES:
            raise SafetyRejection(
                f"job_class {job_spec.job_class!r} not in low-risk allowlist; "
                "outbound/high-risk work stays in the needs-human queue"
            )
        text = self.spec_text(job_spec)
        if not self.sanitiser(text):
            raise SafetyRejection("job spec text failed the sanitise wall (secret detected)")

    @staticmethod
    def spec_text(job_spec: JobSpec) -> str:
        return json.dumps(
            {
                "task": job_spec.task,
                "acceptance_criteria": list(job_spec.acceptance_criteria),
                "safety_bounds": list(job_spec.safety_bounds),
                "payload": dict(job_spec.payload),
            }
        )
