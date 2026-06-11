from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretScanResult:
    available: bool
    found: bool
    detail: str | None


def scan_diff_for_secrets(
    diff_text: str,
    *,
    runner=subprocess.run,
    ggshield_bin: str | None = None,
    timeout: int = 120,
) -> SecretScanResult:
    ggshield = ggshield_bin or shutil.which("ggshield")
    if ggshield is None:
        log.info("ggshield not installed; using keyword fallback")
        return SecretScanResult(available=False, found=False, detail="ggshield not installed")

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as tmp:
            tmp.write(diff_text)
            tmp_path = tmp.name

        completed = runner(
            [ggshield, "secret", "scan", "path", tmp_path, "--json", "--exit-zero"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.warning("ggshield secret scan timed out")
        return SecretScanResult(available=False, found=False, detail="ggshield timeout")
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        if completed.returncode != 0:
            log.warning("ggshield secret scan failed: %s", (completed.stderr or "")[:200])
        else:
            log.warning("ggshield secret scan returned invalid json")
        return SecretScanResult(available=False, found=False, detail="ggshield invalid json")

    incident_count = 0
    detector_types: list[str] = []
    entities = payload.get("entities_with_incidents", []) if isinstance(payload, dict) else []
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            incidents = entity.get("incidents", [])
            if not isinstance(incidents, list):
                continue
            incident_count += len(incidents)
            for incident in incidents:
                if not isinstance(incident, dict):
                    continue
                detector_type = incident.get("type") or incident.get("detector_name")
                if detector_type:
                    detector_types.append(str(detector_type))

    detail = f"ggshield: {incident_count} incident(s)"
    if detector_types:
        detail = f"{detail} [{', '.join(detector_types)}]"

    return SecretScanResult(available=True, found=incident_count > 0, detail=detail)
