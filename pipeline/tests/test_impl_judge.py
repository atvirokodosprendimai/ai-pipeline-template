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


def _file_section(name: str, body_lines: int) -> str:
    lines = "\n".join(f"+line {i} of {name}" for i in range(body_lines))
    return f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n{lines}\n"


def test_realistic_diff_under_raised_cap_is_not_truncated() -> None:
    # The #793 bug: a faithful ~30KB multi-file impl was cut at 16K, dropping the
    # implementing file (pkg/referral/code.go). With the cap sized to the model
    # context, a normal impl passes through whole and every file survives.
    diff = (
        _file_section("main.go", 40)
        + _file_section("pkg/referral/code.go", 400)   # the core implementation
        + _file_section("pkg/referral/store.go", 300)
        + _file_section("pkg/referral/tier.go", 200)
    )
    assert 16_000 < len(diff) < impl_judge.MAX_DIFF_CHARS  # over the OLD cap, under the new
    out = impl_judge._truncate(diff)
    assert out == diff                                   # verbatim — nothing dropped
    assert "pkg/referral/code.go" in out                # implementing file survives


def test_oversized_diff_truncates_at_file_boundaries_not_midhunk() -> None:
    # Three whole file sections, each well-formed; force truncation with a small
    # explicit limit. A kept file must be WHOLE; a dropped file must be ABSENT —
    # never sliced mid-hunk (which corrupts the diff and makes the judge
    # confabulate).
    s1 = _file_section("a.go", 50)
    s2 = _file_section("b.go", 50)
    s3 = _file_section("c.go", 50)
    diff = s1 + s2 + s3
    limit = len(s1) + len(s2) + 5  # room for ~2 sections, not the 3rd
    out = impl_judge._truncate(diff, limit=limit)

    assert s1 in out and s2 in out          # kept files are intact
    assert "diff --git a/c.go" not in out   # dropped file fully absent, not partial
    assert "PARTIAL diff" in out            # model is told the diff is incomplete
    assert "[truncated" in out
    # No mid-line corruption: every non-marker line in the output is a real input line.
    input_lines = set(diff.splitlines())
    for line in out.splitlines():
        if not line or "truncated" in line or "PARTIAL diff" in line:
            continue  # skip the marker's own lines (incl. its boundary blank)
        assert line in input_lines


def test_single_oversized_file_cut_at_line_boundary() -> None:
    # A lone file larger than the limit can't be kept whole — cut at a LINE
    # boundary (never mid-line) and flag it partial.
    big = _file_section("huge.go", 5000)
    out = impl_judge._truncate(big, limit=2000)
    assert "[truncated" in out
    body = out.split("...[truncated", 1)[0]
    # The kept portion ends on a complete line (no dangling partial line).
    assert body.endswith("\n") or body.splitlines()[-1] in set(big.splitlines())


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


def test_main_missing_spec_file_blocks(tmp_path) -> None:
    d = _write(tmp_path, "x.diff", _DIFF)
    rc = main(
        ["--diff-file", d, "--spec-file", str(tmp_path / "nope.spec")],
        judge_fn=lambda *a, **k: Verdict(True, ()),  # would-pass, but spec missing
    )
    assert rc == 1  # fail-closed, not 0


def test_main_forwards_issue(tmp_path) -> None:
    d = _write(tmp_path, "x.diff", _DIFF)
    s = _write(tmp_path, "x.spec", _SPEC)
    seen = {}

    def capturing(diff, spec, *, issue=None):
        seen["issue"] = issue
        return Verdict(True, ())

    main(["--diff-file", d, "--spec-file", s, "--issue", "42"], judge_fn=capturing)
    assert seen["issue"] == 42


# ---- review-hardening: never-raises, dup-key, injection, error paths --------


def test_base_exception_blocks_never_escapes() -> None:
    """SystemExit from the caller must map to fail-closed, never escape judge()
    (an escaping raise could be read as 'check errored/skip' = fail-open)."""

    def system_exit(_payload):
        raise SystemExit(99)

    verdict = judge(_DIFF, _SPEC, http_caller=system_exit)
    assert verdict.passed is False
    assert any("provider error" in r for r in verdict.reasons)


def test_keyboard_interrupt_propagates() -> None:
    def interrupt(_payload):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        judge(_DIFF, _SPEC, http_caller=interrupt)


def test_duplicate_key_response_blocks() -> None:
    content = (
        '{"faithfulness": {"pass": false}, "faithfulness": {"pass": true}, '
        '"safety": {"pass": true}}'
    )
    body = {"choices": [{"message": {"content": content}}]}
    verdict = judge(_DIFF, _SPEC, http_caller=lambda p: body)
    assert verdict.passed is False  # last-wins PASS must NOT slip through
    assert verdict.reasons == ("unparseable judge response",)


def test_urlerror_timeout_blocks() -> None:
    import socket
    import urllib.error

    def timed_out(_payload):
        raise urllib.error.URLError(socket.timeout("timed out"))

    verdict = judge(_DIFF, _SPEC, http_caller=timed_out)
    assert verdict.passed is False
    assert any("provider error" in r for r in verdict.reasons)


def test_http_error_429_blocks() -> None:
    import urllib.error

    def rate_limited(_payload):
        raise urllib.error.HTTPError(None, 429, "Too Many Requests", None, None)

    assert judge(_DIFF, _SPEC, http_caller=rate_limited).passed is False


def test_both_dimensions_fail_lists_both() -> None:
    verdict = judge(_DIFF, _SPEC, http_caller=_caller(False, False, f_reason="bad", s_reason="leak"))
    assert verdict.passed is False
    assert any("faithfulness" in r for r in verdict.reasons)
    assert any("safety" in r for r in verdict.reasons)


def test_empty_reason_uses_fallback() -> None:
    verdict = judge(_DIFF, _SPEC, http_caller=_caller(False, True, f_reason=""))
    assert verdict.passed is False
    assert any(impl_judge._FALLBACK_REASON in r for r in verdict.reasons)


def test_whitespace_content_blocks() -> None:
    body = {"choices": [{"message": {"content": "   "}}]}
    verdict = judge(_DIFF, _SPEC, http_caller=lambda p: body)
    assert verdict.passed is False
    assert verdict.reasons == ("unparseable judge response",)


def test_prompt_fences_untrusted_and_warns_against_injection() -> None:
    prompt = impl_judge._build_prompt("DIFFTEXT", "SPECTEXT", issue=7)
    # untrusted content is fenced and flagged as DATA, not instructions
    assert impl_judge._UNTRUSTED in prompt
    assert "never instructions" in prompt.lower() or "not instructions" in prompt.lower()
    # rubric/output format come AFTER the untrusted blocks
    assert prompt.index("SPECTEXT") < prompt.index("faithfulness:")
    assert prompt.index("DIFFTEXT") < prompt.index("Respond with ONLY")
