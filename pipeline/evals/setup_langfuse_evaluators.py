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

Schemas confirmed against the live instance (probe + OpenAPI example): evaluator
``outputDefinition`` uses ``dataType``+``score``/``reasoning``; rules use
``target`` (observation/experiment), ``evaluator``{name,scope,type}, ``enabled``,
``sampling``, ``filter`` [{type,column,operator,value}], ``mapping`` [{variable,
source}]. ``--probe`` re-dumps the live shape; failures log the full response.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
import sys
import urllib.request
import urllib.error

# --- evaluator definitions (HOW to score) -----------------------------------
# Each judge prompt returns structured output per `outputDefinition`. Models
# MUST support structured output (Langfuse requirement). `{{output}}`/`{{input}}`
# are the evaluator variables, mapped to trace data by the rules below.

# Confirmed via --probe against the live instance: evaluators are
# type=llm_as_judge with a flat `variables` list and an `outputDefinition`
# carrying `dataType` + `score`/`reasoning` sub-objects (descriptions). The
# created Langfuse score takes the evaluator's NAME. modelConfig=null uses the
# project's configured default eval-model connection.
_NUMERIC = {
    "dataType": "NUMERIC",
    "score": {"description": "Score between 0.0 and 1.0 per the rubric in the prompt."},
    "reasoning": {"description": "One sentence reasoning for the score."},
}
_BOOLEAN = {
    "dataType": "BOOLEAN",
    "score": {"description": "1 = passes the check, 0 = fails (a leak was found)."},
    "reasoning": {"description": "One sentence reasoning; name what leaked if any."},
}

# Judge model: GLM-5.2 via the project's "zai" LLM connection (z.ai, anthropic
# adapter). `provider` must match a connection from GET /api/public/llm-connections;
# the connection must offer this `model` (see langfuse-llm-connection workflow).
_JUDGE_MODEL = {"provider": "zai", "model": "GLM-5.2"}

_PIKAPODS_SNAPSHOT = """PikaPods self-hosts these open-source apps (non-exhaustive):
- Zapier / IFTTT -> Activepieces, Automatisch
- Airtable -> Baserow, NocoDB
- Sentry -> Bugsink, GlitchTip
- Google Analytics -> Umami, Matomo
- Slack / Teams -> Mattermost
- Mailchimp / marketing automation -> Mautic, Listmonk
- Salesforce / HubSpot -> Twenty CRM
- Confluence / Notion -> Docmost, BookStack
- Intercom / community support -> Answer
- status / uptime monitoring -> Uptime Kuma
- 1Password / Bitwarden -> Vaultwarden
- Firebase -> Pocketbase, Directus
"""

# Coarse advisory snapshot of capabilities already shipped for wgmesh/cloudroof,
# for measuring the redo class the in-loop capabilities digest prevents (the box
# re-proposing already-built work, e.g. "add web analytics" when OpenPanel ships).
# This static list WILL drift; the live authority is the auto-derived digest in
# `.github/workflows/observation-loop.yml` (the `## Already-Shipped Capabilities`
# block from `company/scripts/collect-capabilities.sh`). This evaluator is an
# advisory measurement signal, not a gate.
_SHIPPED_SNAPSHOT = """Capabilities already shipped (non-exhaustive); re-proposing
any of these is a REDO:
- Web analytics / event / conversion tracking -> OpenPanel, self-hosted at
  counter.hackrsvalv.com, on the cloudroof.eu landing pages (wgmesh PR #762)
- Email capture / newsletter signup form -> Buttondown ("meshletter") form on the
  landing pages (wgmesh PR #764)
- Transactional / outreach email sending -> Unsend
- Payments / checkout / subscription -> Polar checkout CTAs on the landing pages
- Outreach assets (stargazer list, send-ready copy) -> shipped docs (wgmesh PR #763)
- Core product (wgmesh): WireGuard mesh, peer discovery, NAT traversal, gossip,
  encryption, managed ingress
Building a downstream consumer ON TOP of a shipped capability (e.g. a dashboard or
report over data OpenPanel already collects) is NOT a redo.
"""

EVALUATORS = [
    {
        "name": "growth_issue_quality",
        "type": "llm_as_judge",
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
        "outputDefinition": _NUMERIC,
        "modelConfig": _JUDGE_MODEL,
    },
    {
        "name": "impl_faithfulness",
        "type": "llm_as_judge",
        "prompt": (
            "Spec (intended change):\n{{input}}\n\n"
            "Produced diff/implementation:\n{{output}}\n\n"
            "Score 0.0-1.0: does the diff faithfully satisfy the spec, stay in "
            "scope (no unrelated changes), include tests, and avoid referencing "
            "types/files not established by the spec? 1.0 = fully faithful + tested "
            "+ in scope; 0.0 = ignores the spec or sprawls."
        ),
        "variables": ["input", "output"],
        "outputDefinition": _NUMERIC,
        "modelConfig": _JUDGE_MODEL,
    },
    {
        "name": "public_safety_pass",
        "type": "llm_as_judge",
        "prompt": (
            "Text about to be published to a PUBLIC repository:\n{{output}}\n\n"
            "Pass (1) ONLY if it contains NO secrets/API keys, NO customer PII, "
            "and NO exact revenue figures. Otherwise fail (0) and name what "
            "leaked. Semantic backstop to the sanitise.sh wall."
        ),
        "variables": ["output"],
        "outputDefinition": _BOOLEAN,
        "modelConfig": _JUDGE_MODEL,
    },
    {
        "name": "no_component_paywall",
        "type": "llm_as_judge",
        "prompt": (
            "Box-proposed spec or issue:\n{{output}}\n\n"
            "Pass (1) ONLY if the spec/issue gates NO shipped component on "
            "payment, license key, account state, trial/time limit, or remote "
            "authorization. A trial ending may stop the MANAGED service "
            "(cloudroof.eu), but a component must never be disabled. Fail (0) "
            "if a daemon, CLI, dashboard, library, or self-hosted component "
            "would stop, degrade, unlock, route, run, or provide features based "
            "on any of those vectors."
        ),
        "variables": ["output"],
        "outputDefinition": _BOOLEAN,
        "modelConfig": _JUDGE_MODEL,
    },
    {
        "name": "open_source_default",
        "type": "llm_as_judge",
        "prompt": (
            "You are scoring a box-PROPOSED ISSUE on whether it defaults to "
            "open-source / self-hostable tooling instead of proprietary SaaS.\n\n"
            f"{_PIKAPODS_SNAPSHOT}\n"
            "Proposed issue:\n{{output}}\n\n"
            "Rule of thumb: if PikaPods has it, we can use it.\n\n"
            "Score 0.0-1.0 with these anchors: 1.0 = proposal adopts NO "
            "third-party tool/service (NOT APPLICABLE), OR proposes an open-"
            "source/self-hostable tool, OR names a PikaPods app; ~0.5 = "
            "proposes a proprietary SaaS but with explicit justification that "
            "the OSS/PikaPods equivalent cannot meet the need; 0.0 = proposes "
            "a proprietary SaaS where a PikaPods/OSS equivalent plainly exists "
            "(e.g. Intercom->Answer, Zapier->Activepieces), with no "
            "justification. Reasoning: one sentence naming the proprietary "
            "tool and the OSS alternative."
        ),
        "variables": ["output"],
        "outputDefinition": _NUMERIC,
        "modelConfig": _JUDGE_MODEL,
    },
    {
        "name": "redo_of_shipped_capability",
        "type": "llm_as_judge",
        "prompt": (
            "You are scoring a box-PROPOSED ISSUE on whether it RE-PROPOSES a "
            "capability that already shipped — the redo class the Observation "
            "Loop's capabilities digest exists to prevent.\n\n"
            f"{_SHIPPED_SNAPSHOT}\n"
            "Proposed issue:\n{{output}}\n\n"
            "Score 0.0-1.0 with these anchors: 1.0 = proposes genuinely new work, "
            "OR builds a downstream consumer on top of an existing capability, OR "
            "names no capability in the shipped list (NOT APPLICABLE); ~0.5 = "
            "overlaps a shipped capability but plausibly extends or replaces it "
            "for a stated reason; 0.0 = re-proposes adding/implementing a "
            "capability that already ships (e.g. 'add web analytics tracking' when "
            "OpenPanel already tracks, 'add an email signup form' when Buttondown "
            "is live), with no justification. Lower is worse (more of a redo). "
            "Reasoning: one sentence naming the proposed capability and the shipped "
            "one it duplicates, or 'not applicable'."
        ),
        "variables": ["output"],
        "outputDefinition": _NUMERIC,
        "modelConfig": _JUDGE_MODEL,
    },
]

# --- evaluation rules (WHAT to score) ---------------------------------------
# Schema confirmed from the instance OpenAPI example (CreateEvaluationRule):
#   target = "observation" | "experiment"   (NOT "trace")
#   evaluator = {name, scope, type}          (scope filled from create response)
#   enabled = bool; sampling = 0..1
#   filter = [{type:"stringOptions", column, operator:"any of", value:[...]}]
#   mapping = [{variable, source}]
# Filter to type=GENERATION AND exclude the eval worker's own judge LLM calls.
# The judges (LLM-as-judge via langchain) surface as GENERATION observations named
# `ChatAnthropic`; without excluding them the rules RE-SCORE each other's calls
# (recursive feedback, confirmed live 06-19). Box generations are named
# `<stage>-llm` (triage-llm, spec-llm, implement-llm, ...) by emit_generation, so a
# single `name none of ["ChatAnthropic"]` condition excludes the judge calls while
# keeping every box stage. Filter conditions are ANDed.
# (If the unstable API rejects `none of` / `name`, the 400 body enumerates the
# valid operators/columns — fall back to a `name any of [<stage>-llm...]` allowlist
# or a metadata `source=box` match; box generations carry metadata.source=box.)
_GEN_FILTER = [
    {
        "type": "stringOptions",
        "column": "type",
        "operator": "any of",
        "value": ["GENERATION"],
    },
    {
        "type": "stringOptions",
        "column": "name",
        "operator": "none of",
        "value": ["ChatAnthropic"],
    },
]

RULES = [
    {
        "name": "rule_growth_issue_quality",
        "evaluatorName": "growth_issue_quality",
        "target": "observation",
        "sampling": 1.0,
        "filter": _GEN_FILTER,
        "mapping": [{"variable": "output", "source": "output"}],
    },
    {
        "name": "rule_impl_faithfulness",
        "evaluatorName": "impl_faithfulness",
        "target": "observation",
        "sampling": 0.5,
        "filter": _GEN_FILTER,
        "mapping": [
            {"variable": "input", "source": "input"},
            {"variable": "output", "source": "output"},
        ],
    },
    {
        "name": "rule_public_safety_pass",
        "evaluatorName": "public_safety_pass",
        "target": "observation",
        "sampling": 1.0,
        "filter": _GEN_FILTER,
        "mapping": [{"variable": "output", "source": "output"}],
    },
    {
        "name": "rule_no_component_paywall",
        "evaluatorName": "no_component_paywall",
        "target": "observation",
        "sampling": 1.0,
        "filter": _GEN_FILTER,
        "mapping": [{"variable": "output", "source": "output"}],
    },
    {
        "name": "rule_open_source_default",
        "evaluatorName": "open_source_default",
        "target": "observation",
        "sampling": 1.0,
        "filter": _GEN_FILTER,
        "mapping": [{"variable": "output", "source": "output"}],
    },
    {
        "name": "rule_redo_of_shipped_capability",
        "evaluatorName": "redo_of_shipped_capability",
        "target": "observation",
        "sampling": 1.0,
        "filter": _GEN_FILTER,
        "mapping": [{"variable": "output", "source": "output"}],
    },
]

_UNSTABLE = "/api/public/unstable"
_REDO_RULE_NAME = "rule_redo_of_shipped_capability"
_RULE_TIMESTAMP_KEYS = (
    "createdAt",
    "created_at",
    "timestamp",
)


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


def _get_list(path: str) -> list:
    status, payload = _request("GET", path)
    if status != 200 or not isinstance(payload, dict):
        print(f"  GET {path} -> {status} {str(payload)[:200]}")
        return []
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _parse_langfuse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _post_registration_enriched_gen(
    enriched: list, registered_at: str | None
) -> object | None:
    scoreable = [
        gen
        for gen in enriched
        if isinstance(gen, dict)
        and str(gen.get("name", "")).endswith("-llm")
    ]
    if not scoreable:
        return None
    if registered_at is None:
        return scoreable[0]
    registered = _parse_langfuse_time(registered_at)
    if registered is None:
        return scoreable[0]
    for gen in scoreable:
        started = _parse_langfuse_time(gen.get("startTime"))
        if started is not None and started >= registered:
            return gen
    return None


def _has_post_registration_enriched_box_generation(
    enriched: list, registered_at: str | None
) -> bool:
    return _post_registration_enriched_gen(enriched, registered_at) is not None


_VERIFY_EXIT_CODES = {"PASS": 0, "WAIT": 0, "FAIL": 1}


def _verify_exit_code(verdict: str) -> int:
    return _VERIFY_EXIT_CODES[verdict]


def _classify_verify(
    *,
    gens_count: int,
    box_gens: list,
    enriched: list,
    redo_scores: int,
    other_eval_scores: int,
    post_registration_enriched_gen: object | None,
) -> tuple[str, str]:
    if not gens_count:
        return (
            "FAIL",
            "VERIFY: NO GENERATION observations in Langfuse — the box is not emitting "
            "generation traces, so the evaluator has nothing to score (wired but off the "
            "execution path). Instrument the box's LLM calls before this eval can fire.",
        )
    if redo_scores > 0:
        return (
            "PASS",
            f"VERIFY: PASS — {redo_scores} redo_of_shipped_capability score(s) on real "
            "generations. Evaluator is firing end-to-end.",
        )
    if other_eval_scores > 0:
        if post_registration_enriched_gen:
            return (
                "FAIL",
                f"VERIFY: FAIL — the score pipeline is ALIVE ({other_eval_scores} score(s) from sibling "
                "evaluators), and a post-registration enriched box generation exists, but "
                "redo_of_shipped_capability still has zero scores. The redo rule's "
                "GENERATION filter appears broken; inspect the rule filter/mapping before "
                "trusting this evaluator.",
            )
        return (
            "WAIT",
            f"VERIFY: WAIT — the score pipeline is ALIVE ({other_eval_scores} score(s) "
            "from sibling evaluators), but no redo score yet. This is a non-failing "
            "awaiting-the-first-post-registration-generation state; re-run verify after "
            "the next box generation.",
        )
    return (
        "FAIL",
        "VERIFY: FAIL — box generations exist but NO evaluator (redo or sibling) has any "
        "score. The eval-rule -> score path is not firing at all; fix that before trusting "
        "any judge. Check the Langfuse default eval-model connection and rule enablement.",
    )


def verify() -> int:
    """End-to-end check that the redo evaluator is actually scoring real box
    generations: are there GENERATION observations at all, and are
    redo_of_shipped_capability scores landing on them? Registered != firing."""
    gens = _get_list("/api/public/observations?type=GENERATION&limit=50")
    print(f"GENERATION observations (latest 50 sampled): {len(gens)}")
    for g in gens[:5]:
        if isinstance(g, dict):
            print(f"  - {g.get('startTime')} name={g.get('name')} trace={g.get('traceId')}")

    # DIAGNOSTIC: the eval rules map {{output}} <- observation.output. If real box
    # generations carry no text output (only token-count usage), the judges score
    # an empty field. Dump the first generation's input/output + a few score
    # reasonings to confirm what the judge actually sees.
    if gens and isinstance(gens[0], dict):
        g0 = gens[0]
        print("DIAG first GENERATION observation fields:")
        print(f"  output={json.dumps(g0.get('output'))[:200]}")
        print(f"  input={json.dumps(g0.get('input'))[:200]}")
        print(f"  usageDetails={json.dumps(g0.get('usageDetails') or g0.get('usage'))[:200]}")

    # U4: box generations (name `<stage>-llm`, emit_generation) must carry deliverable
    # text after the enrich fix (U1/U2). Judge self-calls are named `ChatAnthropic`
    # and are now filtered out of scoring (U3). Distinguish "enrichment live" from
    # "box still emitting empty output" (fix not deployed to the box yet).
    box_gens = [
        g for g in gens if isinstance(g, dict) and str(g.get("name", "")).endswith("-llm")
    ]
    enriched = [g for g in box_gens if g.get("output")]
    print(
        f"box generations (<stage>-llm): {len(box_gens)}, with non-empty output: {len(enriched)}"
    )
    if box_gens and not enriched:
        print(
            "DIAG box generations carry EMPTY output — enrichment (U1/U2) not yet live on "
            "the box; the judges still score nothing until the box deploys this fix."
        )

    # All recent scores, tallied by evaluator name — distinguishes "redo rule
    # just hasn't seen a post-registration generation yet" (other evaluators ARE
    # scoring → pipeline alive) from "no evaluator has ever scored" (score
    # pipeline dead, independent of the redo addition).
    all_scores = _get_list("/api/public/scores?limit=100") or _get_list(
        "/api/public/v2/scores?limit=100"
    )
    # DIAGNOSTIC: dump a few score reasonings. If the judge saw an empty {{output}},
    # the reasoning reads generic / "not applicable" and NUMERIC values default high.
    print("DIAG sample score reasonings:")
    for s in all_scores[:6]:
        if isinstance(s, dict):
            print(
                f"  - {s.get('name')} value={s.get('value')} "
                f"comment={json.dumps(s.get('comment'))[:160]}"
            )
    by_name: dict[str, int] = {}
    for s in all_scores:
        if isinstance(s, dict) and s.get("name"):
            by_name[str(s["name"])] = by_name.get(str(s["name"]), 0) + 1
    # Live Langfuse names each score after its RULE (e.g. `rule_open_source_default`),
    # not the evaluator — confirmed from the instance, contradicting older assumptions.
    # Count both forms so the check is robust to either naming.
    def _count(ev_name: str) -> int:
        return by_name.get(ev_name, 0) + by_name.get(f"rule_{ev_name}", 0)

    our_names = {ev["name"] for ev in EVALUATORS}
    redo_scores = _count("redo_of_shipped_capability")
    other_eval_scores = sum(
        _count(ev) for ev in our_names if ev != "redo_of_shipped_capability"
    )
    print(f"recent scores by name (latest 100 sampled): {by_name or '{}'}")
    print(f"redo_of_shipped_capability scores: {redo_scores}")

    print("---")
    redo_registered_at = _redo_rule_registered_at()
    post_registration_enriched_gen = _post_registration_enriched_gen(
        enriched, redo_registered_at
    )
    verdict, message = _classify_verify(
        gens_count=len(gens),
        box_gens=box_gens,
        enriched=enriched,
        redo_scores=redo_scores,
        other_eval_scores=other_eval_scores,
        post_registration_enriched_gen=post_registration_enriched_gen,
    )
    print(message)
    return _verify_exit_code(verdict)


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


def _existing_rule_items() -> list:
    status, payload = _request("GET", f"{_UNSTABLE}/evaluation-rules")
    if status != 200 or not isinstance(payload, dict):
        return []
    items = (
        payload.get("data")
        or payload.get("evaluators")
        or payload.get("evaluationRules")
        or []
    )
    if not isinstance(items, list):
        return []
    return items


def _existing_rule_ids() -> dict[str, str]:
    items = _existing_rule_items()
    if not items:
        return {}
    return {
        str(item["name"]): str(item["id"])
        for item in items
        if isinstance(item, dict) and item.get("name") and item.get("id")
    }


def _redo_rule_registered_at() -> str | None:
    for item in _existing_rule_items():
        if (
            isinstance(item, dict)
            and str(item.get("name", "")) == _REDO_RULE_NAME
        ):
            for key in _RULE_TIMESTAMP_KEYS:
                value = item.get(key)
                if value:
                    return str(value)
    return None


def apply(dry_run: bool) -> int:
    if dry_run:
        for ev in EVALUATORS:
            print(f"[dry-run] POST {_UNSTABLE}/evaluators\n{json.dumps(ev, indent=2)}")
        for rule in RULES:
            print(
                f"[dry-run] POST {_UNSTABLE}/evaluation-rules\n{json.dumps(rule, indent=2)}"
            )
        return 0

    # Phase 1: evaluators. Capture each one's real `scope` from the response so
    # the rules reference it correctly (custom-created scope is not guessable).
    scope_by_name: dict[str, str] = {}
    ev_fail = 0
    for ev in EVALUATORS:
        status, payload = _request("POST", f"{_UNSTABLE}/evaluators", ev)
        exists_ok = status == 409 and (
            "name_conflict" in str(payload) or "already exists" in str(payload)
        )
        ok = status in (200, 201) or exists_ok
        if ok and isinstance(payload, dict) and payload.get("scope"):
            scope_by_name[ev["name"]] = str(payload["scope"])
        result = "exists (idempotent ok)" if exists_ok else ("OK" if ok else payload)
        print(f"evaluator {ev['name']}: {status} {result}")
        ev_fail += 0 if ok else 1

    # Phase 2: rules. Build the evaluator reference object {name, scope, type}
    # — scope comes from the create response (custom evaluators are "project").
    rule_fail = 0
    existing_rule_ids = _existing_rule_ids()
    for rule in RULES:
        ev_name = str(rule["evaluatorName"])
        body = {
            "name": rule["name"],
            "evaluator": {
                "name": ev_name,
                "scope": scope_by_name.get(ev_name, "project"),
                "type": "llm_as_judge",
            },
            "target": rule["target"],
            "enabled": True,
            "sampling": rule["sampling"],
            "filter": rule["filter"],
            "mapping": rule["mapping"],
        }
        rule_id = existing_rule_ids.get(str(rule["name"]))
        if rule_id:
            status, payload = _request(
                "PATCH", f"{_UNSTABLE}/evaluation-rules/{rule_id}", body
            )
        else:
            status, payload = _request("POST", f"{_UNSTABLE}/evaluation-rules", body)
        exists_ok = status == 409 and (
            "name_conflict" in str(payload) or "already exists" in str(payload)
        )
        ok = status in (200, 201) or exists_ok
        result = "exists (idempotent ok)" if exists_ok else ("OK" if ok else payload)
        print(f"rule {rule['name']}: {status} {result}")
        rule_fail += 0 if ok else 1

    print(
        f"summary: evaluators {len(EVALUATORS) - ev_fail}/{len(EVALUATORS)} ok, "
        f"rules {len(RULES) - rule_fail}/{len(RULES)} ok"
    )
    return ev_fail + rule_fail


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
    parser.add_argument(
        "--verify",
        action="store_true",
        help="check the redo evaluator is scoring real box generations end-to-end",
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
    if args.verify:
        return verify()
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
