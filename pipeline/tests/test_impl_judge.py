"""Tests for the fail-closed impl-judge (pipeline/evals/impl_judge.py).

The cardinal contract: NO path returns passed=True / exit 0 without an explicit
parsed PASS on both dimensions. Every error/ambiguity branch must block.
All tests inject the http_caller / judge_fn — no network.
"""

from __future__ import annotations

import json

import pytest

from evals import impl_judge
from evals.impl_judge import Verdict, judge, main

pytestmark = pytest.mark.unit

_DIFF = "diff --git a/x.go b/x.go\n+func F() {}\n"
_SPEC = "Add function F to package x."


def _caller(faithful: bool, safe: bool, *, f_reason: str = "", s_reason: str = ""):
    body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "faithfulness": {"pass": faithful, "reason": f_reason},
                            "safety": {"pass": safe, "reason": s_reason},
                        }
                    )
                }
            }
        ]
    }
    return lambda payload: body


# ---- judge() fail-closed matrix ------------------------------------------


def test_both_pass_returns_passed_true() -> None:
    verdict = judge(_DIFF, _SPEC, http_caller=_caller(True, True))
    assert verdict == Verdict(True, ())


def test_faithfulness_fail_blocks_and_names_gap() -> None:
    verdict = judge(_DIFF, _SPEC, http_caller=_caller(False, True, f_reason="ignores spec"))
    assert verdict.passed is False
    assert any("faithfulness" in r and "ignores spec" in r for r in verdict.reasons)


def test_safety_fail_blocks_with_reason() -> None:
    verdict = judge(_DIFF, _SPEC, http_caller=_caller(True, False, s_reason="leaked API key"))
    assert verdict.passed is False
    assert any("safety" in r and "leaked API key" in r for r in verdict.reasons)


def test_empty_diff_blocks_without_calling() -> None:
    called = []
    verdict = judge("   ", _SPEC, http_caller=lambda p: called.append(p) or {})
    assert verdict == Verdict(False, ("missing diff",))
    assert called == []


def test_empty_spec_blocks_without_calling() -> None:
    called = []
    verdict = judge(_DIFF, "", http_caller=lambda p: called.append(p) or {})
    assert verdict == Verdict(False, ("missing spec",))
    assert called == []


def test_caller_raises_blocks_never_true() -> None:
    def boom(_payload):
        raise RuntimeError("connreset")

    verdict = judge(_DIFF, _SPEC, http_caller=boom)
    assert verdict.passed is False
    assert any("provider error" in r for r in verdict.reasons)


def test_garbage_response_blocks_unparseable() -> None:
    verdict = judge(_DIFF, _SPEC, http_caller=lambda p: {"nonsense": 1})
    assert verdict.passed is False
    assert verdict.reasons == ("unparseable judge response",)


def test_missing_dimension_field_blocks() -> None:
    body = {"choices": [{"message": {"content": '{"faithfulness": {"pass": true}}'}}]}
    verdict = judge(_DIFF, _SPEC, http_caller=lambda p: body)
    assert verdict.passed is False
    assert verdict.reasons == ("unparseable judge response",)


def test_non_bool_pass_blocks() -> None:
    content = '{"faithfulness": {"pass": "yes"}, "safety": {"pass": true}}'
    body = {"choices": [{"message": {"content": content}}]}
    verdict = judge(_DIFF, _SPEC, http_caller=lambda p: body)
    assert verdict.passed is False
    assert verdict.reasons == ("unparseable judge response",)


def test_oversized_diff_truncated_before_caller() -> None:
    big = "X" * (impl_judge.MAX_DIFF_CHARS + 5000)
    captured = {}

    def capture(payload):
        captured["content"] = payload["messages"][0]["content"]
        return _caller(True, True)(payload)

    judge(big, _SPEC, http_caller=capture)
    sent = captured["content"]
    assert "[truncated" in sent
    assert big not in sent  # full untruncated diff never sent


def test_purity_same_inputs_same_verdict() -> None:
    caller = _caller(False, True, f_reason="x")
    assert judge(_DIFF, _SPEC, http_caller=caller) == judge(_DIFF, _SPEC, http_caller=caller)


# ---- main() exit-code mapping --------------------------------------------


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_main_pass_returns_0(tmp_path, capsys) -> None:
    d = _write(tmp_path, "x.diff", _DIFF)
    s = _write(tmp_path, "x.spec", _SPEC)
    rc = main(["--diff-file", d, "--spec-file", s], judge_fn=lambda *a, **k: Verdict(True, ()))
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_main_fail_returns_1(tmp_path, capsys) -> None:
    d = _write(tmp_path, "x.diff", _DIFF)
    s = _write(tmp_path, "x.spec", _SPEC)
    rc = main(
        ["--diff-file", d, "--spec-file", s],
        judge_fn=lambda *a, **k: Verdict(False, ("safety: leaked",)),
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out and "leaked" in out


def test_main_missing_diff_file_blocks(tmp_path) -> None:
    s = _write(tmp_path, "x.spec", _SPEC)
    rc = main(
        ["--diff-file", str(tmp_path / "nope.diff"), "--spec-file", s],
        judge_fn=lambda *a, **k: Verdict(True, ()),  # would-pass, but file missing
    )
    assert rc == 1  # fail-closed, not 0


def test_main_missing_key_real_path_returns_2(tmp_path, monkeypatch, capsys) -> None:
    for name in impl_judge._KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    d = _write(tmp_path, "x.diff", _DIFF)
    s = _write(tmp_path, "x.spec", _SPEC)
    rc = main(["--diff-file", d, "--spec-file", s])  # default judge_fn → real path
    assert rc == 2
    assert "missing API key" in capsys.readouterr().err
