"""Shared fixtures/helpers for the Self-Heal test files (cutover U4)."""

from __future__ import annotations

from pathlib import Path

from wgmesh_pipeline.selfheal import SelfHealInputs

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = REPO_ROOT / "company" / "pipeline-health-state.json"

NOW = "2026-06-12T17:21:49Z"
SIGNALS_NOW = "2026-06-12T17:21:48Z"
STALE = "2026-06-10T00:00:00Z"  # > 48h before NOW: stale for every sweep
FRESH = "2026-06-12T17:00:00Z"

ENDPOINTS_OK = tuple(
    {"name": name, "url": f"https://{name}.example", "status": 200}
    for name in ("chimney", "cloudroof", "coroot", "tvcentras")
)
CLAUDE_MD = "# wgmesh\n## Architecture\nmesh\n## Build\nmake\n"


class NoCallForge:
    """The runner must not touch the forge when inputs are complete."""

    def __getattr__(self, name: str):
        raise AssertionError(f"runner must not call forge.{name}")


def issue(number: int, title: str = "t", created: str = STALE, labels=()) -> dict:
    return {
        "number": number, "title": title, "createdAt": created,
        "labels": [{"name": name} for name in labels],
    }


def pr(number: int, title: str, updated: str = STALE, labels=()) -> dict:
    return {
        "number": number, "title": title, "updatedAt": updated,
        "labels": [{"name": name} for name in labels],
    }


def make_inputs(**overrides) -> SelfHealInputs:
    base = dict(
        now=NOW, run_id="run-1", needs_human_issues=(),
        endpoints=ENDPOINTS_OK, claude_md_text=CLAUDE_MD,
        signals_now=SIGNALS_NOW,
    )
    base.update(overrides)
    return SelfHealInputs(**base)


def kinds(run) -> list[str]:
    return [action.kind for action in run.actions]
