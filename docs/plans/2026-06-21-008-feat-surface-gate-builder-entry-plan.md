---
title: "feat: surface gate at the builder entry — keep service issues out of the wgmesh impl pipeline"
date: 2026-06-21
type: feat
status: planned
depth: standard
origin: docs/brainstorms/2026-06-21-cloudroof-issue-routing-gate-requirements.md
---

# feat: Surface gate at the builder entry

**Target repo:** ai-pipeline-template (box code; gates the wgmesh impl pipeline)

## Summary

A surface-aware gate between triage and spec that makes it structurally impossible for a cloudroof (service) or unclassified issue to be built in the wgmesh impl pipeline. It classifies the issue's surface (reading the label, else an LLM call), and for service / unresolvable-unknown surfaces it blocks the spec→impl path and parks the issue for human decision via labels — which is exactly the input the Quackback gtm-decision stream keys on. Directly prevents the #783 class: a manually-filed cloudroof issue (`fn:dev`, no surface label) that reached the wgmesh builder, was respecced as a daemon feature, built off-spec, and rejected by the judge.

## Problem Frame

PR #1931 shipped surface routing (`observation.py:48–256`, `_route_lane_and_repo` → `cloudroof-eu`) but it fires **only inside the observation loop** (LLM-ideated issues). Three entry paths bypass it: manually-filed issues never hit routing (`observation.py` processes only LLM assessments — #783's path), `triage.py` has no surface check, and there is no fail-safe on unknown surface at the builder. So service/unclassified issues still flow triage → spec → implement in the wgmesh pipeline. The judge catches the output, but the spec+impl+judge cost is already spent.

The graph runs linearly per issue (`graph/build.py::CompiledGraph.invoke` and `graph/build_lg.py` for langgraph): `triage → spec → spec_pr → implement-ladder → gate`. There is already one pre-spec escape — `classification in {wont-do, needs-info} → escalate(needs-human), return`. The surface gate is a second escape on the same seam.

## Requirements (origin)

- **R1** — Classify surface on every issue entering the builder, including manual/unlabeled ones (reuse the gather surface prompt).
- **R2** — Load-bearing builder gate: `surface:service` never reaches spec→impl; unknown surface blocks until classified (does not default to product).
- **R3** — Route detected service issues toward the cofounder decision gate (Quackback gtm-decision stream).
- **R4** — Fail-safe by default: any ambiguity resolves to the human queue, never a silent wgmesh build.
- **R5** — Reuse #1931 surface infra (`_resolve_surface`, labels), don't duplicate.

## Key Technical Decisions

- **KTD1 — Gate is a new step on the triage→spec seam, wired into BOTH graph impls.** Mirror the existing `wont-do/needs-info → escalate, return` escape in `CompiledGraph.invoke`, and add the equivalent branch to `build_lg.py::route_after_triage` (+ a node). Wiring both paths is load-bearing — a gate in only one impl is bypassable by `config.graph_impl`.
- **KTD2 — Surface resolution reuses `observation._resolve_surface(labels)`; unlabeled → LLM-classify.** No new classifier primitive. An issue with no `surface:*` label is classified from title+body using the gather surface prompt (`observation_gather.py:290–301`), and the resolved `surface:*` label is **applied** (persisted) so the decision is idempotent and visible to the contract.
- **KTD3 — Disposition is park-in-place, not GitHub relocation.** A blocked service issue gets `surface:service` + `needs-human` and stays where it is; no `gh issue transfer`. This honors the "moving out of GitHub" direction — the box-side gate is substrate-agnostic, and re-homing to cloudroof-eu is the cutover/Quackback layer's job, not this gate's.
- **KTD4 — Quackback gtm-decision wiring needs no separate emit.** Per `docs/quackback-decision-streams.md`, the stream is a **label-keyed view**: `surface:service` + `needs-human` → gtm-decision; `surface:product` + `needs-human` → product-decision; missing surface + `needs-human` → product-decision (fail-safe) + log. Producing those labels IS the wiring; the decision layer (feat/quackback-decision-layer) consumes them.
- **KTD5 — "Block unknown" governs building, not review routing.** An unresolvable-unknown issue is blocked from the wgmesh builder (never specs) AND parked via `needs-human` (no surface → product-decision fail-safe per contract). "Don't default to product" (R2) is about not *building* it as product, not about which review stream a human sees it in.

## High-Level Technical Design

Per-issue flow with the gate inserted (both graph impls):

```
triage ──▶ classification in {wont-do, needs-info}? ──yes──▶ escalate(needs-human) ▶ return
   │                                                              (existing escape)
   no
   ▼
SURFACE GATE (new)
   resolve surface: _resolve_surface(issue.labels)
     └─ None? → LLM classify(title, body) → (surface, confidence); apply surface:* label
   decide:
     product (confident)        → proceed to spec  (the only build path)
     service                    → apply surface:service + needs-human ▶ escalate ▶ return
     unknown / low-confidence   → apply needs-human (no surface) + log ▶ escalate ▶ return
   ▼ (product only)
spec ──▶ spec_pr ──▶ implement-ladder ──▶ gate
```

The block branches reuse the existing escalate/return shape: set `decision="escalate"`, add the labels, append `visited`, return — the issue never reaches `self.spec()`. The gtm-decision / product-decision stream a human sees is then derived from the labels by the Quackback layer (KTD4), no extra call.

## Implementation Units

### U1. Surface resolution + classification

**Goal:** Given an issue, resolve its surface (product|service|unknown) from labels, classifying via LLM when no `surface:*` label is present, and apply the resolved label.
**Requirements:** R1, R5.
**Dependencies:** none.
**Files:**
- `pipeline/wgmesh_pipeline/graph/nodes/surface_gate.py` (new)
- `pipeline/tests/test_surface_gate.py` (new)
**Approach:** Export `resolve_issue_surface(issue, *, classifier_fn=None) -> SurfaceResolution` (surface: `"product"|"service"|"unknown"`, confidence, source: `"label"|"classified"`). Read labels via the existing `observation._resolve_surface`. When it returns None, call the injected `classifier_fn(title, body)` (the LLM surface classifier reusing the gather surface prompt; injected so tests run without a model). Low/zero confidence → `"unknown"`. Caller applies the `surface:*` label when source is `"classified"` (via forge `add_label`, mode-gated like other writes).
**Patterns to follow:** `observation.py::_resolve_surface` (label read), `observation_gather.py:290–301` (surface prompt), the injected-callable test idiom in `company/scripts/conflict-heal/run.py`.
**Test scenarios:**
- Issue with `surface:service` label → `("service", high, "label")`, no classifier call.
- Issue with `surface:product` label → `("product", …, "label")`.
- Issue with NO surface label, classifier returns service → `("service", …, "classified")`.
- No surface label, classifier returns product → `("product", …, "classified")`.
- No surface label, classifier low/zero confidence or error → `("unknown", …)`; classifier exception surfaces as unknown, never silently product.
- Both `surface:product` and `surface:service` present (contradiction) → service wins (gated), matching `_resolve_surface` precedence.

### U2. Gate decision (pure)

**Goal:** Map a resolved surface to a gate verdict the graph acts on.
**Requirements:** R2, R4.
**Dependencies:** U1.
**Files:**
- `pipeline/wgmesh_pipeline/graph/nodes/surface_gate.py` (modify)
- `pipeline/tests/test_surface_gate.py` (modify)
**Approach:** Export pure `decide_surface_gate(resolution) -> verdict` where verdict ∈ `{"build", "block_service", "block_unknown"}`. product+confident → `build`; service → `block_service`; unknown/low-confidence → `block_unknown`. No I/O. The graph wiring (U3) maps verdicts to label-application + escalate.
**Test scenarios:**
- product/high → `build`.
- service (label or classified) → `block_service`.
- unknown → `block_unknown`.
- product but low confidence → `block_unknown` (fail-safe: don't build on a shaky product guess).
- Determinism: same resolution → same verdict.

### U3. Wire the gate into both graph impls + block disposition

**Goal:** Run the surface gate between triage and spec in both execution paths; block_service / block_unknown apply the parking labels and escalate without reaching spec.
**Requirements:** R2, R3, R4 (KTD1, KTD3, KTD4).
**Dependencies:** U1, U2.
**Files:**
- `pipeline/wgmesh_pipeline/graph/build.py` (modify — `CompiledGraph.invoke`, after the wont-do/needs-info escape, before `self.spec`)
- `pipeline/wgmesh_pipeline/graph/build_lg.py` (modify — `route_after_triage` + a surface-gate node)
- `pipeline/tests/test_graph.py` and/or `pipeline/tests/test_build_lg_parity.py` (modify)
**Approach:** Insert the gate call after triage. On `block_service`: apply `surface:service` (if not already labeled) + `needs-human`, set `decision="escalate"`, append `visited`, return — never call `self.spec`. On `block_unknown`: apply `needs-human` (no surface label) and log the missing-surface case (contract fail-safe → product-decision), escalate, return. On `build`: proceed to spec unchanged. In `build_lg.py`, `route_after_triage` returns a new `"surface_gate"` route (or folds into `"escalate"`) so the langgraph path blocks identically. Reuse the forge `add_label` already used by the existing escalate. Mode-gated writes (shadow → dry-run, spec-only → blocked) inherited from the forge.
**Patterns to follow:** the existing `wont-do/needs-info` escape in `build.py::invoke`; `build_lg.py::route_after_triage` / `escalate`.
**Test scenarios:**
- `surface:service` issue → does NOT reach spec (assert `spec` not in `visited`); ends with `surface:service` + `needs-human`; `decision == "escalate"`. (Legacy AND langgraph.)
- Manual issue, no surface label, classifier→service → classified, blocked, labeled, no spec.
- Unknown/low-confidence issue → blocked, `needs-human` applied, missing-surface logged, no spec.
- `surface:product` issue → proceeds to spec (assert `spec` in `visited`).
- Parity: legacy `CompiledGraph` and langgraph `build_lg` produce the same block/proceed decision for the same issue.
- wont-do/needs-info still escapes first (gate doesn't change the existing pre-spec escape).

### U4. gtm-decision stream conformance + observability

**Goal:** Prove the gate's output satisfies the Quackback decision-stream contract and surfaces the missing-surface signal.
**Requirements:** R3 (KTD4), R4.
**Dependencies:** U3.
**Files:**
- `pipeline/tests/test_surface_gate.py` (modify) or a small `pipeline/tests/test_gtm_stream_conformance.py` (new)
**Approach:** Assert the contract conformance examples from `docs/quackback-decision-streams.md`: a gate-blocked service issue carries `surface:service` + `needs-human` (→ gtm-decision stream); an unresolvable-unknown carries `needs-human` with no surface (→ product-decision fail-safe) and the missing-surface case is logged. No new emit code — this unit verifies the label output is contract-correct, since the stream is a label-keyed view.
**Test scenarios:**
- Covers contract example 1: `surface:service` + `needs-human` present → routes gtm-decision, not product-decision.
- Covers contract example 2: `needs-human` + no surface → product-decision fail-safe AND missing-surface logged.
- A built (product) issue carries no `needs-human` (it went to spec, not the decision queue).

## Scope Boundaries

### In scope
- Surface classification at the builder entry (incl. manual/unlabeled issues).
- The gate in both graph impls; block service + unknown before spec.
- Park-in-place disposition (`surface:service`/`needs-human`) feeding the Quackback gtm-decision stream by label.

### Deferred to follow-up
- The cloudroof-eu autonomous builder (a pipeline pointed at cloudroof-eu).
- goal-sprint dual-surface emission (#1931 U4).
- Backfilling/reclassifying the existing aged wgmesh backlog of service issues.
- Active relocation of issues to cloudroof-eu (left to the cutover/Quackback re-home layer).

### Outside this product's identity
- Monetizing or gating wgmesh itself — revenue lives only at the cloudroof layer (CONSTITUTION.md). This gate enforces the boundary; it does not move it.

## Risks & Dependencies

- **Classifier reliability** — an LLM mis-classifying a real product issue as service would wrongly block it. Mitigated by R4 fail-safe (low confidence → block_unknown → human, never silent), and the human can re-label. The cost of a false service-classification is a human review, not a bad merge.
- **Both-graph drift** — if the gate lands in only one graph impl, the other path leaks service issues. U3 parity test is load-bearing.
- **Quackback liveness** — the gtm-decision stream is a contract/label-view; if the decision layer (feat/quackback-decision-layer) is not yet consuming labels, blocked service issues still park safely via `needs-human` (no regression — they simply wait in the human queue). No hard dependency.
- **Reuse dependency** — `observation._resolve_surface` and the gather surface prompt are the reused primitives; no new secrets or external calls beyond the existing LLM classifier path.

## Open Questions (execution-time)

- Exact LLM call wiring for the unlabeled-classification path — reuse the gather model/client factory; resolve concrete client wiring during implementation.
- Whether `route_after_triage` should return a distinct `"surface_gate"` route or fold the block into the existing `"escalate"` route in langgraph — decide when touching `build_lg.py` (both yield the same no-spec outcome).

## Sources & Research

- Origin: `docs/brainstorms/2026-06-21-cloudroof-issue-routing-gate-requirements.md`.
- Surface infra (reuse): `pipeline/wgmesh_pipeline/observation.py:48–58, 203–256`; `observation_gather.py:290–301`.
- Graph seams: `pipeline/wgmesh_pipeline/graph/build.py::CompiledGraph.invoke` (wont-do/needs-info escape), `graph/build_lg.py::route_after_triage`, `graph/nodes/triage.py`.
- Decision-stream contract: `docs/quackback-decision-streams.md` (#1931 U7 — label-keyed streams, conformance examples).
- Forge label/status surface: `pipeline/wgmesh_pipeline/forge/quackback.py`, `forge/quackback_status.py`.
- Root incident: `[[feedback_offspec_impl_malformed_transcript_spec]]`, `[[project_product_service_split]]`.
