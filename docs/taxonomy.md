---
name: ai-pipeline-template taxonomy
last_updated: "2026-09-10"
status: current
---

# Taxonomy

Shared domain vocabulary for this project — structured classification axes that govern how every
work item, artifact, and decision is categorised. Source-of-truth for each axis is named;
cross-references between axes are noted.

This doc formalises what `CONCEPTS.md` seeds as prose. Where CONCEPTS provides the *story*,
this doc provides the *index*.

---

## Axis 1 — Surface

What the work item touches: the public repo surface it lands on.

| Value | Meaning | Source |
|---|---|---|
| `product` | WireGuard mesh software (wgmesh) | [STRATEGY.md — Key metrics](../STRATEGY.md) |
| `service` | Managed hosting at cloudroof.eu | [STRATEGY.md — surface:service](../STRATEGY.md) |
| `meta` | This repo (ai-pipeline-template) itself | [STRATEGY.md — product vs. meta](../STRATEGY.md) |

**Rule:** Every GitHub issue and PR carries a `surface:` label. Product code → wgmesh;
service code → cloudroof-eu; go-to-market needing human capital or pricing → `needs-human` /
Quackback queue. The product itself is never paywalled (PROD-3).

---

## Axis 2 — Funnel Stage (company state)

Where the company is in its customer-acquisition journey. Drives the Observation Loop's
assessment. Assessed daily; inferred from real signals, not assumptions.

| Value | Label | Exit criterion | Source |
|---|---|---|---|
| 0 | Foundation | Core product works end-to-end | [system-prompt.md §The funnel](../company/system-prompt.md) |
| 1 | Dogfood | Team uses product daily, no critical bugs ≥ 7 days | ditto |
| 2 | Presence | Landing page live, quickstart published, install works | ditto |
| 3 | Reachable | Open Collective billing live with tiers + first recurring contribution | ditto |
| 4 | Pipeline | First customer onboarded from personal network | ditto |
| 5 | Revenue | First invoice paid, customer active ≥ 30 days | ditto |

**Rule:** The Observation Loop infers the current stage and creates/closes issues to advance it.
Billing attaches to the managed layer only (PROD-3).

---

## Axis 3 — Work-item Stage (pipeline position)

Where a work item sits in the build lane. Carried entirely by the GitHub label — the label *is*
the state.

| Value | Label | Gate | Source |
|---|---|---|---|
| `copilot-triaging` | Triage | Spec written, routed by `fn:` | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| `spec` | Spec | Structural validation + human review | ditto |
| `fn:*` | Routing | Route to correct lane (dev/ops/gtm/billing/support/legal) | [AGENTS.md](../AGENTS.md) |
| `awaiting-build` | Build queue | Spec approved, Goose dispatched | ditto |
| `impl` | Implementation | Code written against approved spec | ditto |
| `awaiting-review` | Review | Code review + guardrail check | ditto |
| `approved` | Approved | Human reviewer signed off | ditto |
| `merged` | Merged | PR merged, issue auto-closed | ditto |

---

## Axis 4 — Routing Function

The company concern a work item belongs to. One value per issue; determines which lane in the
convergence engine processes it.

| Value | Covers |
|---|---|
| `fn:dev` | Product engineering (wgmesh) |
| `fn:ops` | Infrastructure (Terraform, NixOS, WireGuard) |
| `fn:gtm` | Go-to-market (content, outreach, positioning) |
| `fn:billing` | Revenue, pricing, payment collection |
| `fn:support` | Customer onboarding, documentation |
| `fn:legal` | Licensing, compliance, data |

**Source:** [AGENTS.md — pipeline routing](../AGENTS.md) + [system-prompt.md — issue labels](../company/system-prompt.md)

---

## Axis 5 — Track

The strategic dimension a work item ladders up to. One of three.

| Value | Scope | Source |
|---|---|---|
| Convergence engine | Triage → spec → impl → merge → deploy loop | [STRATEGY.md — Tracks](../STRATEGY.md) |
| Self-heal & resilience | Health monitoring, circuit breaker, escalation | ditto |
| Customer Factory / Revenue | cloudroof.eu, billing, distribution | ditto |

---

## Axis 6 — Work-item Kind

The type of artifact, not its stage.

| Kind | Definition | Source |
|---|---|---|
| Issue | Root work item, label-carried stage | [CONCEPTS.md — Work items](../CONCEPTS.md) |
| Spec | Design proposal delivered as PR; gate for code | [CONCEPTS.md — Spec](../CONCEPTS.md) |
| Implementation | Code fulfilling an approved spec; PR + review | [CONCEPTS.md — Implementation](../CONCEPTS.md) |
| Assessment | Dated decision record from one Observation Loop run | [CONCEPTS.md — Assessment](../CONCEPTS.md) |
| Clog | Stuck work item surfaced by the Supervisor | [CONCEPTS.md — Supervisor](../CONCEPTS.md) |
| Decision | Durable ADR (Accepted/Superseded/Withdrawn) | [AGENTS.md — authoritative docs](../AGENTS.md) |

---

## Axis 7 — Loop

Which autonomous loop owns the work item.

| Loop | Role | Governs | Source |
|---|---|---|---|
| Observation Loop | Assesses company state daily; creates/closes Issues | *What* work enters the pipeline | [CONCEPTS.md](../CONCEPTS.md) |
| Convergence Engine | Drives one item through stages to merge | *How* work moves through the pipeline | ditto |
| Self-Healing | Re-triggers stalled stages deterministically | Recovery without escalation | ditto |
| Supervisor | Ranks Clogs by dwell time; read-only | Surfaces worst blockers | ditto |

---

## Relationships

- **Funnel stage (Axis 2)** drives which issues the Observation Loop creates.
- **Routing function (Axis 4)** + **Work-item stage (Axis 3)** together determine which agent acts.
- **Surface (Axis 1)** determines which repo a PR lands in.
- **Track (Axis 5)** determines which strategic goal an item ladders up to.
- **Loop (Axis 7)** determines which autonomous system is responsible.

