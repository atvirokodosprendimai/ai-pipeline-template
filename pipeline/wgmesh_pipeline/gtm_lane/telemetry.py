"""Best-effort lane telemetry (U9).

Records per-item outcome counts, total cost, and last latency to a state file the
pulse reads. **Best-effort**: a telemetry write must NEVER block or fail a lane
run (the telemetry-must-be-best-effort learning) — any IO error is swallowed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from wgmesh_pipeline.gtm_lane.executor import ItemStatus

log = logging.getLogger("wgmesh_pipeline.gtm_lane.telemetry")


def record_outcome(
    status: ItemStatus,
    *,
    state_path: str | Path,
    cost: float | None = None,
    latency_s: float | None = None,
    make_parents: bool = True,
) -> None:
    """Append one item's outcome to the telemetry state file. Swallows all
    errors — telemetry is never allowed to break the lane."""
    try:
        path = Path(state_path)
        if make_parents:
            path.parent.mkdir(parents=True, exist_ok=True)
        data = _load(path)
        data["counts"][status.value] = data["counts"].get(status.value, 0) + 1
        if cost is not None:
            data["total_cost"] = round(data.get("total_cost", 0.0) + cost, 6)
        if latency_s is not None:
            data["last_latency_s"] = latency_s
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 — best-effort; never block the lane
        log.warning("gtm telemetry write failed (best-effort, ignored)", exc_info=True)


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("counts", {})
        return data
    except (OSError, json.JSONDecodeError):
        return {"counts": {}, "total_cost": 0.0}
