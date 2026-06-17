"""Register Langfuse LLM-as-a-Judge evaluators + rules — version-controlled, idempotent.

Codifies the box's eval setup so it survives Langfuse rebuilds and is reviewable
in git instead of click-ops. Targets the Langfuse v3 **unstable** public API
(deployed instance is v3.181):

    POST /api/public/unstable/evaluators        (HOW to score: prompt, vars, output, model)
    POST /api/public/unstable/evaluation-rules   (WHAT to score: target, filter, sampling, mapping)

Auth = Basic (LANGFUSE_PUBLIC_KEY:LANGFUSE_SECRET_KEY), same creds the tracer uses.

Run (standalone; needs the three LANGFUSE_* env vars except for --dry-run):
    python pipeline/evals/setup_langfuse_evaluators.py --probe     # dump live schema first
    python pipeline/evals/setup_langfuse_evaluators.py --dry-run    # print payloads, no writes
    python pipeline/evals/setup_langfuse_evaluators.py              # create/version evaluators + rules

CAVEAT (unstable API): field names follow the documented camelCase shape. Run
``--probe`` once against an evaluator you created in the UI to confirm the exact
``variableMapping`` / ``filter`` shape for this instance, then adjust RULES if a
POST returns 400 (the full response body is logged on failure).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.error

# --- evaluator definitions (HOW to score) -----------------------------------
# Each judge prompt returns structured output per `outputDefinition`. Models
# MUST support structured output (Langfuse requirement). `{{output}}`/`{{input}}`
# are the evaluator variables, mapped to trace data by the rules below.

_MODEL = {
    "provider": "default",
    "model": "default",
}  # uses the project's configured eval model connection

EVALUATORS = [
    {
        "name": "growth_issue_quality",
        "prompt": (
            "You are scoring an issue the autonomous growth loop proposed for "
            "wgmesh/cloudroof. Company goal: PAID CUSTOMERS.\n\n"
            "Proposed issue:\n{{output}}\n\n"
            "Score 0.0-1.0 on ALL of: (1) concrete & shippable (one task an agent "
            "or marketer can execute end-to-end), not a vague theme; (2) tied to "
            "paid-customer acquisition with an explicit goal link (trials->paid); "
            "(3) has an acceptance check + a metric it should move; (4) customer-"
            "facing/revenue-advancing, NOT internal pipeline/infra busywork. "
            "1.0 = all four, 0.0 = none."
        ),
        "variables": ["output"],
        "outputDefinition": {"type": "NUMERIC", "name": "growth_issue_quality"},
        "modelConfig": _MODEL,
    },
    {
        "name": "impl_faithfulness",
        "prompt": (
            "Spec (intended change):\n{{input}}\n\n"
            "Produced diff/implementation:\n{{output}}\n\n"
            "Score 0.0-1.0: does the diff faithfully satisfy the spec, stay in "
            "scope (no unrelated changes), include tests, and avoid referencing "
            "types/files not established by the spec? 1.0 = fully faithful + tested "
            "+ in scope; 0.0 = ignores the spec or sprawls."
        ),
        "variables": ["input", "output"],
        "outputDefinition": {"type": "NUMERIC", "name": "impl_faithfulness"},
        "modelConfig": _MODEL,
    },
    {
        "name": "public_safety_pass",
        "prompt": (
            "Text about to be published to a PUBLIC repository:\n{{output}}\n\n"
            "Return true ONLY if it contains NO secrets/API keys, NO customer PII, "
            "and NO exact revenue figures. Otherwise return false and name what "
            "leaked. This is a semantic backstop to the sanitise.sh wall."
        ),
        "variables": ["output"],
        "outputDefinition": {"type": "BOOLEAN", "name": "public_safety_pass"},
        "modelConfig": _MODEL,
    },
]

# --- evaluation rules (WHAT to score) ---------------------------------------
# target: live observations/traces. filter: which ones (by name). samplingRate
# 0..1. variableMapping: evaluator variable -> source field on the trace data.
# NOTE: confirm the exact mapping/filter shape with --probe (unstable API).

RULES = [
    {
        "name": "rule_growth_issue_quality",
        "evaluatorName": "growth_issue_quality",
        "target": "trace",
        "samplingRate": 1.0,
        "filter": [{"column": "name", "operator": "contains", "value": "observation"}],
        "variableMapping": [
            {
                "variableName": "output",
                "langfuseObject": "trace",
                "selectedColumnId": "output",
            },
        ],
    },
    {
        "name": "rule_impl_faithfulness",
        "evaluatorName": "impl_faithfulness",
        "target": "observation",
        "samplingRate": 1.0,
        "filter": [{"column": "name", "operator": "contains", "value": "implement"}],
        "variableMapping": [
            {
                "variableName": "input",
                "langfuseObject": "observation",
                "selectedColumnId": "input",
            },
            {
                "variableName": "output",
                "langfuseObject": "observation",
                "selectedColumnId": "output",
            },
        ],
    },
    {
        "name": "rule_public_safety_pass",
        "evaluatorName": "public_safety_pass",
        "target": "observation",
        "samplingRate": 1.0,
        "filter": [{"column": "name", "operator": "contains", "value": "spec_pr"}],
        "variableMapping": [
            {
                "variableName": "output",
                "langfuseObject": "observation",
                "selectedColumnId": "output",
            },
        ],
    },
]

_UNSTABLE = "/api/public/unstable"


def _auth_header() -> str:
    pk = os.environ["LANGFUSE_PUBLIC_KEY"]
    sk = os.environ["LANGFUSE_SECRET_KEY"]
    token = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    return f"Basic {token}"


def _request(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    host = os.environ["LANGFUSE_HOST"].rstrip("/")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{host}{path}",
        data=data,
        method=method,
        headers={"Authorization": _auth_header(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def probe() -> None:
    """Dump existing evaluators + rules so the exact live schema can be confirmed
    before trusting the field names below (unstable API)."""
    for path in (f"{_UNSTABLE}/evaluators", f"{_UNSTABLE}/evaluation-rules"):
        status, payload = _request("GET", path)
        print(f"\n=== GET {path} -> {status} ===")
        print(
            json.dumps(payload, indent=2)[:4000]
            if isinstance(payload, (dict, list))
            else payload
        )


def _existing_names(path: str, key: str = "data") -> set[str]:
    status, payload = _request("GET", path)
    if status != 200 or not isinstance(payload, dict):
        return set()
    items = (
        payload.get(key)
        or payload.get("evaluators")
        or payload.get("evaluationRules")
        or []
    )
    return {str(i.get("name")) for i in items if isinstance(i, dict) and i.get("name")}


def apply(dry_run: bool) -> int:
    failures = 0
    for ev in EVALUATORS:
        if dry_run:
            print(f"[dry-run] POST {_UNSTABLE}/evaluators\n{json.dumps(ev, indent=2)}")
            continue
        status, payload = _request("POST", f"{_UNSTABLE}/evaluators", ev)
        ok = status in (200, 201)
        print(f"evaluator {ev['name']}: {status} {'OK' if ok else payload}")
        failures += 0 if ok else 1
    for rule in RULES:
        if dry_run:
            print(
                f"[dry-run] POST {_UNSTABLE}/evaluation-rules\n{json.dumps(rule, indent=2)}"
            )
            continue
        status, payload = _request("POST", f"{_UNSTABLE}/evaluation-rules", rule)
        ok = status in (200, 201)
        print(f"rule {rule['name']}: {status} {'OK' if ok else payload}")
        failures += 0 if ok else 1
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register Langfuse LLM-as-judge evaluators + rules"
    )
    parser.add_argument(
        "--probe", action="store_true", help="GET + dump live evaluators/rules schema"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print payloads, do not write"
    )
    args = parser.parse_args(argv)
    if not args.dry_run:  # dry-run prints payloads only, never hits the API
        for key in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            if not os.environ.get(key):
                print(f"missing env: {key}", file=sys.stderr)
                return 2
    if args.probe:
        probe()
        return 0
    failures = apply(args.dry_run)
    if failures:
        print(
            f"{failures} write(s) failed — see responses above (unstable API: verify shape with --probe)",
            file=sys.stderr,
        )
        return 1
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
