---
title: "GTM rent-a-human executor: drain the service-decision queue autonomously"
type: brainstorm
date: 2026-06-24
status: requirements
surface: service
---

# GTM rent-a-human executor

## Summary

Give the `surface:service` GTM-decision queue a real autonomous executor: a new
pipeline lane that takes an approved, low-risk GTM job, dispatches it to a
**rented human** (human-as-a-service API), verifies completion, and closes the
loop — so service go-to-market drains without the cofounder doing the work by
hand. A WISDOM-grounded job-draft step and a cloudroof positioning + Mom-Test
validation kit ride along as sub-components.

---

## Problem Frame

The product engineering pipeline has converged — the last four pulses show the
wgmesh backlog drained, CI green, and **0 paid customers**. STRATEGY.md is blunt:
"converging on code without converging on revenue is theatre." The gating
constraint is demand/monetization, not engineering.

Grounding traced the specific stall: the Observation Loop already biases toward
GTM work and emits `surface:service` issues, but every non-code GTM item is
labelled `needs-human` and parked in a cofounder-only decision queue with **no
executor after approval**. Even a sound GTM decision (run outreach, set pricing,
build a list) has nothing that carries it out. The queue grows; nothing ships.

The cofounder-as-executor *is* the babysitting failure STRATEGY commits to
removing. The pipeline's whole premise is autonomy — so the executor should be a
rented human dispatched by the pipeline, not the founder. That reframes a
proposal-quality problem (which a WISDOM-corpus injection would address) into a
**delivery** problem (which needs an executor with a verification loop).

Serves STRATEGY *Customer Factory / Revenue surface* track — owns paid customers.

---

## Key Decisions

- **Executor is a rented human, not the cofounder.** The lane dispatches GTM
  jobs to an API-addressable human-task service. This removes the cofounder-only
  bottleneck and keeps "no babysitting." Accepts a new external dependency and
  per-task cost.

- **Delivery is the constraint, not proposal quality.** Grounding confirmed
  decisions stall *after* approval for lack of an executor. So the lane is the
  primary deliverable; the WISDOM/GTM-learnings injection is demoted to a
  grounding sub-component of the job-draft step (it grounds what the executor
  does, never an off-path proposal).

- **Low-risk job class first.** The MVP executor runs only low-blast-radius work
  (lead research, list-building, manual signups/account creation, content QA,
  competitor recon, data entry). Outbound contact as the company (cold outreach,
  posting) stays gated until the dispatch+verify loop is proven.

- **Validation and buildout run in parallel (Traction 50% rule).** The lane
  doesn't gate behind a validation sprint; the cloudroof positioning frame +
  Mom-Test kit are prepared alongside, with the actual stargazer conversations
  deferred behind the risk boundary.

- **Verification mirrors the impl-judge gate.** A rented human spending money and
  touching brand needs a fail-closed completion check, or the lane is a worse
  off-path than the current queue.

- **Budget approval is an envelope, not per-task.** The cofounder approves a
  spend envelope once (via the existing decision-lane); the executor draws
  against it per job. Per-task human approval would reintroduce the bottleneck.

---

## Actors

- **Observation Loop** — emits `surface:service` GTM issues, labels lane
  (`fn:dev` vs `needs-human`). Unchanged.
- **Cofounder** — approves the spend envelope and the GTM strategy once; no
  longer the per-job executor.
- **GTM-execution lane (new)** — drafts the job spec, enforces the budget gate,
  dispatches to the human-task service, runs verification, closes the item.
- **Rented human (external)** — executes the dispatched low-risk job, returns
  proof of completion.
- **Verifier** — fail-closed check that the returned work matches the job spec
  and safety bounds before the item closes.

---

## Key Flows

**Primary: a low-risk GTM job from queue to closed.**

1. An approved `surface:service` + `needs-human` item that is low-risk-classified
   enters the GTM-execution lane.
2. The lane drafts a **job spec** (task, acceptance criteria, safety bounds),
   grounded by the GTM-learnings corpus.
3. **Budget gate:** the job's estimated cost is checked against the remaining
   envelope. Over budget or no envelope → park, do not dispatch.
4. The lane dispatches the job spec to the human-task service.
5. The rented human completes it and returns a result + proof.
6. **Verification:** a fail-closed check compares result against the job spec's
   acceptance criteria and safety bounds. Pass → close the item, record cost.
   Fail → retry or escalate (never silently close).
7. Loop telemetry (cost, pass/fail, latency) feeds the pulse.

**Fail-open principle:** any lane error parks the item back in the queue in its
prior state — the lane never loses or corrupts a queued decision.

---

## Requirements

**Executor lane (R1–R4)**

- **R1.** A new GTM-execution lane consumes approved `surface:service` items that
  are classified low-risk, and is the autonomous executor for them.
- **R2.** Each item produces a structured job spec (task, acceptance criteria,
  safety bounds) before any dispatch.
- **R3.** The lane dispatches job specs to an API-addressable human-task service
  and ingests the returned result + completion proof.
- **R4.** Any lane error returns the item to the queue in its prior state; the
  lane never drops, duplicates, or corrupts a queued decision (fail-open).

**Job-class safety boundary (R5–R7)**

- **R5.** The MVP executor accepts only low-risk job classes: lead research,
  list-building, manual signups/account creation, content QA, competitor recon,
  data entry.
- **R6.** Outbound contact as the company (cold outreach, social posting,
  customer-facing messaging) is rejected by the lane until explicitly enabled
  after the loop is proven.
- **R7.** No job may emit secrets, customer PII, or exact revenue figures in its
  spec or its returned artifact; the existing sanitise wall applies to both
  directions.

**Verification & budget (R8–R10)**

- **R8.** A fail-closed verifier checks every returned result against the job
  spec's acceptance criteria and safety bounds before the item closes.
- **R9.** A failed verification retries or escalates to `needs-human`; it never
  silently closes the item.
- **R10.** Spend is gated against a cofounder-approved envelope drawn per job;
  exceeding or lacking an envelope parks the item rather than dispatching.

**GTM-learnings grounding (R11–R12)**

- **R11.** The job-draft step is grounded by a local GTM-learnings corpus,
  reusing the shipped `select_learnings`/`write_learnings_file` seam
  (`pipeline/wgmesh_pipeline/learnings.py`), keyed on the job/decision text.
- **R12.** The GTM corpus is vendored into this repo (the WISDOM corpus lives in
  a sibling repo and cannot be globbed from this deploy); grounding is fail-open
  and never blocks a job.

**Validation kit (R13–R15)**

- **R13.** Produce a cloudroof positioning frame using the Obviously Awesome
  components (competitive alternatives incl. self-hosting, unique attributes,
  value, target segment, category).
- **R14.** Produce a Mom-Test discovery kit (question script that probes past
  behavior, not pitch; target-segment definition).
- **R15.** Build the stargazer target list as a low-risk executor job (R5); the
  actual outbound conversations are deferred behind R6.

---

## Acceptance Examples

- **Low-risk job, verified pass:** a "build a 50-row competitor-pricing sheet"
  job → spec drafted → within envelope → dispatched → returned sheet passes the
  verifier's acceptance criteria → item closes, cost recorded.
- **Outbound job rejected:** a "cold-email the stargazer list" item reaches the
  lane → R6 rejects it as not-yet-enabled → stays in queue, not dispatched.
- **Over-budget:** an approved low-risk job whose estimate exceeds the remaining
  envelope → parked at the budget gate, cofounder notified, no dispatch.
- **Verification fail:** returned work omits half the acceptance criteria →
  verifier fails → retry or escalate to `needs-human`, item stays open.
- **Grounding empty:** no GTM learning matches the job → empty grounding, job
  proceeds unchanged (fail-open).

---

## Scope Boundaries

### Deferred for later

- **Outbound GTM as the company** (cold outreach, posting, customer messaging) —
  enabled only after the dispatch+verify loop is proven on low-risk jobs (R6).
- **Actual stargazer validation conversations** — the kit and target list are
  prepared here; running the conversations waits on the risk boundary.
- **Installing the cloudroof code-build instance** — the executor for
  *code-buildable* GTM (landing/signup); its own stalled brainstorm
  (`docs/brainstorms/2026-06-22-cloudroof-service-funnel-requirements.md`). A
  parallel dependency, not built here.
- **WISDOM-injection into the decision-proposal recipe** — proposal quality is
  not the constraint; revisit only if approved decisions start stalling on
  draft quality rather than execution.

### Outside this product's identity

- **Cofounder-as-executor** — reverting GTM execution to a human-in-the-loop
  queue contradicts the "no babysitting" thesis; the whole point is to remove it.
- **Paywalling product capability** — monetization stays at the managed-service
  layer per CONSTITUTION.md; nothing here gates wgmesh functionality.
- **Self-modifying GTM strategy** — the lane executes approved jobs; it does not
  set pricing, strategy, or brand voice (those remain cofounder decisions).

---

## Dependencies / Assumptions

- **Load-bearing dependency: an API-addressable human-task service with
  completion proof, reachable within budget.** If none exists, the lane has no
  executor and reduces to today's queue. Validate this exists before planning
  commits (Resolve Before Planning).
- **Assumption:** the existing decision-lane (`wgmesh-decision-proposal.yaml`,
  `decision_lane/proposal_runner.py`) is the right home for the envelope
  approval and the new lane's plumbing.
- **Assumption:** the sanitise wall (`company/scripts/sanitise.sh`) can gate
  job specs and returned artifacts in both directions.
- **Dependency:** the GTM-learnings corpus must be authored/vendored into the
  repo before R11–R12 carry value (distilled from the WISDOM corpus +
  `docs/solutions/` GTM learnings).

---

## Outstanding Questions

### Resolve Before Planning

- Which human-task service(s) meet the API + completion-proof + budget bar? This
  gates the lane's feasibility.
- What is the initial spend envelope and who refreshes it?

### Deferred to Planning

- How verification proof is structured per job class (screenshot, artifact diff,
  third-party check) and how the fail-closed verifier scores it.
- Whether the GTM-execution lane is a new `decision_lane` sibling module or an
  extension of the proposal runner.
- Cost/latency telemetry shape for the pulse.

---

## Sources / Research

- STRATEGY.md — *Customer Factory / Revenue surface* track; product-vs-service
  split; paid-customers metric; "code without revenue is theatre."
- Pulse trend: `docs/pulse-reports/2026-06-24_07-08.md` (0 customers, backlog
  drained, service converging in code, demand is the gating constraint).
- Learnings-injection seam to mirror: `pipeline/wgmesh_pipeline/learnings.py`
  (`select_learnings`, `write_learnings_file`); call sites in
  `graph/nodes/spec.py`, `graph/nodes/implement.py` (PR #1988).
- Decision-lane seam: `pipeline/recipes/wgmesh-decision-proposal.yaml`,
  `pipeline/wgmesh_pipeline/decision_lane/proposal_runner.py`,
  `observation_gather.py` (GTM bias + surface/lane labelling).
- Social drip: `.github/workflows/wgmesh-social-drip.yml` (copy generation,
  Mixpost human-review gate).
- Cloudroof code-executor (parallel dep):
  `docs/brainstorms/2026-06-22-cloudroof-service-funnel-requirements.md`.
- GTM corpus source: `ai-vektorius-lt/WISDOM.compiled.md` (31-book GTM stack;
  TRIGGER→book index; Mom Test, Obviously Awesome, Monetizing Innovation,
  100M Leads, Traction).
- CONCEPTS.md — Surface, Escalation, Social Drip, No-component-paywall.
