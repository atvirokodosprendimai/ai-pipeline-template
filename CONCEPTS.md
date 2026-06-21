# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Relationships

The pipeline converges a Seed into a shipped product by moving work items through stages. An Issue is the root work item; triage produces a Spec, an approved Spec produces an Implementation, and a merged Implementation closes the originating Issue. Stage is carried entirely by the work item's label, so the label *is* the state. Two named loops drive this from opposite ends: the Observation Loop decides *what* work to create, and the Convergence Engine drives each created item *through* to merge and deploy. Self-Healing watches the same items and re-triggers whichever stage has stalled.

## The loops

### Observation Loop
The daily cycle that collects signals (GitHub activity, infra health, costs, contributions), assesses the company's current state, and creates or closes Issues to pursue the highest-leverage actions. Owns the loop-state it writes and the daily Assessment it emits; it decides *what* enters the pipeline, not how work moves through it.

### Convergence Engine
The agent loop that drives a single work item through triage → spec → implementation → merge → deploy without a human in the loop. Distinct from the Observation Loop: the Observation Loop chooses work, the Convergence Engine completes it. "Converging" means reaching a finished, deployed product — not merely generating code that still needs babysitting.

### Self-Healing
Deterministic (code, never LLM) recovery that detects work items stalled too long in a stage and re-triggers the responsible workflow, typically by toggling the stage label off and back on. Before acting it checks for an already-in-flight downstream artifact and skips if work is genuinely progressing. Governed by the Circuit Breaker.
*Avoid:* pipeline-health (that is the workflow that runs Self-Healing, not the concept).

### Assessment
The Observation Loop's dated decision record for one run — the state it read, the funnel stage it inferred, and the actions it chose. Each run appends one Assessment to the loop history.

### Supervisor
The ranking pass that snapshots open work items across repos, classifies each into a pipeline stage, and ranks the worst Clogs by dwell time weighted by how much downstream work they block, then recommends one action per Clog. Read-only: it surfaces and recommends, it does not act.

## Work items

### Issue
The root unit of pipeline work, carrying its current stage as a GitHub label. An Issue's label determines its position in the pipeline and which agent or workflow acts on it next. An Issue is closed automatically when the Implementation fulfilling it merges.

### Spec
The design proposal for an Issue, written by the Spec writer during triage and delivered as a spec pull request. A Spec is structurally validated and approved before any code is written against it.
*Avoid:* spec PR (that is the delivery vehicle; the Spec is the content).

### Implementation
The code change that fulfills an approved Spec, produced by the Build agent and delivered as an implementation pull request. Reviewed and guardrail-checked before auto-merge; its merge is what closes the originating Issue.
*Avoid:* impl PR, build.

### Seed
A product idea the founder plants for the pipeline to converge into a shipped, deployed product. Seeds are the things the pipeline exists to finish and take to revenue; a Seed reaching public beta is a milestone, and each Seed owns its own path to a first paying customer.
*Avoid:* seed product.

## Stage control and status

### Clog
A work item stuck in a stage and blocking pipeline flow, severe in proportion to how long it has dwelled and how much downstream work waits on it. The Supervisor's unit of attention: the pipeline's worst Clogs are what get ranked and recommended for action.

### Circuit Breaker
The safety mechanism that stops Self-Healing from cascading within a single run — once too many recovery actions or errors occur in one run, remaining healing is skipped and a human escalation is raised. Resets at the start of the next run rather than latching into a disabled state.

### Escalation
The handoff of a work item to a human when automated recovery is exhausted or a safety limit trips, marked by a dedicated needs-human state. An escalated item can be auto-closed later if resolution signals appear.
*Avoid:* needs-human (that is the label; Escalation is the act).

### Surface
Which funnel owns a work item: **product** (the wgmesh AGPL mesh software, filed in `wgmesh`) or **service** (the cloudroof managed-hosting go-to-market, filed in `cloudroof-eu`). Carried by a `surface:product` / `surface:service` label and orthogonal to the work item's pipeline stage. Routing picks the repo by Surface and the lane by Surface plus kind: product and service *code* flow to the build lane; service go-to-market needing capital, pricing, or human outreach stays in the human queue. wgmesh measures product traction; cloudroof measures service revenue.
*Avoid:* seed repo (a single Surface is not the whole seed).

### Funnel stage
The company's overall maturity position along a fixed ladder — Foundation, Dogfood, Presence, Reachable, Pipeline, Revenue — inferred each run to decide where leverage is highest. Distinct from a work item's pipeline stage: the Funnel stage describes the whole company, a pipeline stage describes one Issue.

### Function label
A tag classifying a work item by the business function it serves (development, ops, go-to-market, billing, support, legal) rather than by its pipeline stage. Stage labels and function labels coexist on the same Issue.

## Agent roles

The pipeline defines roles, not tools — any conforming agent can fill a role.

### Spec writer
The agent role that analyzes a freshly triaged Issue and produces its Spec.

### Build agent
The agent role that reads an approved Spec and produces the Implementation. Currently defaulted to Goose, but the role is tool-agnostic.
*Avoid:* Goose (a current implementation of the role, not the role).

### Observer
The model role that reads collected state during the Observation Loop and produces the Assessment.

## Outbound

### Social Drip
The weekly cadence that auto-drafts one short social post for the product's public accounts and pings a human to review and publish — never posting unattended. Each run is one of two modes: a **ship-news** post highlighting a user-facing change that shipped, or, when nothing user-facing shipped, an **evergreen** post (a rotating educational/positioning angle) so the cadence never goes dark. Distinct from the daily release-notes digest, which is an internal email summary, not a public post.

## Principles and metrics

### Andon
The project's foundational stop-the-line principle: when a defect, failing check, or broken build appears, halt and fix the root cause before passing work downstream rather than working around it. Any contributor — human or agent — has both the authority and the obligation to stop the line.

### Autonomous-ship rate
The share of seeded Specs that reach merge and deploy with zero human intervention — the leading metric for whether the pipeline truly converges without babysitting.

### MSC
The count of paying subscribers across seeded products — the project's lagging revenue north-star, tracked on the dashboard and excluding subscriptions from unrelated products.

### No component paywall
The product value that no shipped product component may gate functionality on payment, license key, account state, trial/time limit, or remote authorization. Every component ships AGPL and full-functionality; a self-hoster gets 100% of the software, offline, forever. Monetization attaches only to the **managed-service layer**, never to withholding capability — "open product, paid hosting," not open-core.
*Avoid:* no-paywall (state the full principle; it binds every seeded product, not one feature).

### Component vs managed-service layer
The boundary that monetization attaches to. A **component** is anything shipped to or run on a user's machine, or constituting the product's core capability (e.g. the wgmesh daemon, CLI, dashboard, libraries) — never paywalled. The **managed-service layer** is the infrastructure the company operates on the user's behalf (cloudroof.eu: hosting, ingress, support, SLA) — the only paid surface. A trial ending stops the operated service; it never disables software the user runs themselves.

### Hollow-green
A passing test suite that proves nothing about the real behavior, because the asserted path is satisfied by a stub, fake, or mock rather than the production code — so a green run coexists with a live failure. The recurring shape in this project: a safety guard or agent-output path is mocked to always cooperate, so the actual failure mode never executes until production.
*Avoid:* false green.

A related failure is a **never-run-path**: production code that no test ever exercises, so its first execution is on the live system. The fix for both is the same — drive a test through the lowest real boundary (the subprocess result, the HTTP layer), reproduce the production symptom, and confirm the test bites by reverting the fix.

## Flagged ambiguities

- "The loop" had been used for both the work-selection cycle and the work-completion cycle — these are distinct: the **Observation Loop** chooses work, the **Convergence Engine** completes it.
- "Pipeline stage" (a single Issue's position) and "Funnel stage" (the whole company's maturity) are different ladders; do not conflate them.
