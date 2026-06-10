from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UsageTotals:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    requests: int
    skipped: int


def default_logs_dir() -> Path:
    return Path.home() / ".local/state/goose/logs"


def snapshot_usage_logs(logs_dir: Path) -> dict[str, int]:
    if not logs_dir.exists():
        return {}
    return {
        path.name: path.stat().st_size
        for path in logs_dir.glob("llm_request.*.jsonl")
        if path.is_file()
    }


def collect_usage_delta(logs_dir: Path, snapshot: dict[str, int]) -> UsageTotals:
    if not logs_dir.exists():
        return UsageTotals(input_tokens=0, output_tokens=0, total_tokens=0, requests=0, skipped=0)

    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    requests = 0
    skipped = 0

    for path in sorted(logs_dir.glob("llm_request.*.jsonl")):
        if not path.is_file():
            continue
        offset = snapshot.get(path.name, 0)
        try:
            size = path.stat().st_size
            if offset < 0 or offset > size:
                offset = 0
            # Iterate lazily: a busy implement run appends megabytes of request
            # payloads between snapshot and collection.
            with path.open("rb") as fh:
                fh.seek(offset)
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        usage = _usage_from_line(line)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        skipped += 1
                        continue
                    input_tokens += usage["input_tokens"]
                    output_tokens += usage["output_tokens"]
                    total_tokens += usage["total_tokens"]
                    requests += 1
        except OSError:
            skipped += 1
            continue

    return UsageTotals(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        requests=requests,
        skipped=skipped,
    )


def _usage_from_line(line: bytes) -> dict[str, int]:
    payload = json.loads(line.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("usage log line must be an object")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise TypeError("usage log line missing usage object")
    return {
        "input_tokens": _int_usage(usage, "input_tokens"),
        "output_tokens": _int_usage(usage, "output_tokens"),
        "total_tokens": _int_usage(usage, "total_tokens"),
    }


def _int_usage(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key)
    if not isinstance(value, int):
        raise TypeError(f"usage.{key} must be an int")
    return value
