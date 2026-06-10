from __future__ import annotations

import json

from wgmesh_pipeline.goose.usage import collect_usage_delta, snapshot_usage_logs


def _append_jsonl(path, rows) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            if isinstance(row, str):
                fh.write(row + "\n")
            else:
                fh.write(json.dumps(row) + "\n")


def test_snapshot_and_delta_reads_only_appended_bytes_and_new_shards(tmp_path) -> None:
    shard = tmp_path / "llm_request.1.jsonl"
    _append_jsonl(
        shard,
        [
            {"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}},
            {"usage": {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9}},
        ],
    )
    snapshot = snapshot_usage_logs(tmp_path)

    _append_jsonl(
        shard,
        [
            {"usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}},
            "not-json",
            {"data": {"id": "x"}, "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}},
        ],
    )
    _append_jsonl(
        tmp_path / "llm_request.2.jsonl",
        [{"usage": {"input_tokens": 5, "output_tokens": 6, "total_tokens": 11}}],
    )

    totals = collect_usage_delta(tmp_path, snapshot)

    assert totals.input_tokens == 18
    assert totals.output_tokens == 30
    assert totals.total_tokens == 48
    assert totals.requests == 3
    assert totals.skipped == 1


def test_missing_logs_dir_has_empty_snapshot_and_zero_totals(tmp_path) -> None:
    missing = tmp_path / "missing"

    assert snapshot_usage_logs(missing) == {}
    assert collect_usage_delta(missing, {}).total_tokens == 0
