from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

pytest.importorskip("langfuse")

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from evals import setup_langfuse_evaluators as mod  # noqa: E402
from evals.setup_langfuse_evaluators import (  # noqa: E402
    EVALUATORS,
    RULES,
    _BOOLEAN,
    _GEN_FILTER,
    _JUDGE_MODEL,
    main,
)


def _no_component_paywall_evaluator() -> dict:
    matches = [ev for ev in EVALUATORS if ev["name"] == "no_component_paywall"]

    assert len(matches) == 1
    return matches[0]


def _no_component_paywall_rule() -> dict:
    matches = [rule for rule in RULES if rule["name"] == "rule_no_component_paywall"]

    assert len(matches) == 1
    return matches[0]


def _plain_text_rubric_score(output: str) -> int:
    evaluator = _no_component_paywall_evaluator()
    rendered = evaluator["prompt"].replace("{{output}}", output)
    text = rendered.lower()

    assert "{{output}}" not in rendered
    assert "pass (1) only if" in text
    assert "fail (0)" in text
    if any(
        marker in text
        for marker in (
            "expire-trial",
            "mesh daemons stop routing if expired",
            "trial_expired=true",
            "trial expiration paywall",
        )
    ):
        return 0
    return 1


@pytest.mark.unit
def test_no_component_paywall_evaluator_shape_and_prompt() -> None:
    evaluator = _no_component_paywall_evaluator()

    assert evaluator["type"] == "llm_as_judge"
    assert evaluator["variables"] == ["output"]
    assert evaluator["outputDefinition"] is _BOOLEAN
    assert evaluator["modelConfig"] is _JUDGE_MODEL
    assert "{{output}}" in evaluator["prompt"]
    assert "payment, license key, account state, trial/time limit, or remote authorization" in evaluator["prompt"]
    assert "A trial ending may stop the MANAGED service (cloudroof.eu)" in evaluator["prompt"]
    assert "a component must never be disabled" in evaluator["prompt"]


@pytest.mark.unit
def test_no_component_paywall_rule_shape() -> None:
    rule = _no_component_paywall_rule()

    assert rule["evaluatorName"] == "no_component_paywall"
    assert rule["target"] == "observation"
    assert rule["sampling"] == 1.0
    assert rule["filter"] is _GEN_FILTER
    assert rule["mapping"] == [{"variable": "output", "source": "output"}]


@pytest.mark.unit
def test_no_component_paywall_rejects_wgmesh_766_fixture() -> None:
    output = """
Build trial expiration paywall: upgrade modal + mesh pause on day 14

Add an expire-trial API that sets trial_expired=true on the account. Once
expired, mesh daemons stop routing if expired so unpaid users must upgrade.
The dashboard should show an upgrade modal and the daemon should refuse to
route traffic until the account is current.
"""

    assert _plain_text_rubric_score(output) == 0


@pytest.mark.unit
def test_no_component_paywall_allows_managed_layer_billing_spec() -> None:
    output = """
Build cloudroof signup and invoice collection for the managed ingress service.
When a cloudroof trial ends, stop only company-operated hosting and managed
ingress for that account. The wgmesh daemon, CLI, dashboard, and libraries keep
full functionality for self-hosted users and are not changed by billing state.
"""

    assert _plain_text_rubric_score(output) == 1


@pytest.mark.unit
def test_no_component_paywall_allows_self_host_full_functionality_spec() -> None:
    output = """
Document and test that self-hosted wgmesh includes full functionality in the
daemon, CLI, dashboard, and libraries. There is no license key, no phone-home,
no account state dependency, no trial/time limit, and no remote authorization
required for any shipped component to run indefinitely.
"""

    assert _plain_text_rubric_score(output) == 1


@pytest.mark.unit
def test_apply_twice_against_stub_endpoint_keeps_409_idempotent(monkeypatch) -> None:
    seen_evaluators: set[str] = set()
    seen_rules: set[str] = set()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._send(200, {"data": []})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            name = body["name"]
            if self.path == f"{mod._UNSTABLE}/evaluators":
                if name in seen_evaluators:
                    self._send(409, {"code": "name_conflict", "message": "already exists"})
                    return
                seen_evaluators.add(name)
                self._send(201, {"scope": "project"})
                return
            if self.path == f"{mod._UNSTABLE}/evaluation-rules":
                if name in seen_rules:
                    self._send(409, {"code": "name_conflict", "message": "already exists"})
                    return
                seen_rules.add(name)
                self._send(201, {})
                return
            self._send(404, {"error": "not found"})

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LANGFUSE_HOST", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    try:
        assert main([]) == 0
        assert main([]) == 0
    finally:
        server.shutdown()
        thread.join()


@pytest.mark.unit
def test_dry_run_prints_no_component_paywall_without_writing(monkeypatch, capsys) -> None:
    def fail_request(_method: str, _path: str, _body=None) -> tuple[int, object]:
        raise AssertionError("--dry-run must not write")

    monkeypatch.setattr(mod, "_request", fail_request)

    assert main(["--dry-run"]) == 0

    captured = capsys.readouterr()
    assert "no_component_paywall" in captured.out
    assert "rule_no_component_paywall" in captured.out
