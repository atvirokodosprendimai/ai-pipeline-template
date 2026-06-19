---
date: 2026-06-19
topic: capabilities-grounding-redo-prevention
---

# Capabilities Grounding — Stop Autobuilders Re-Proposing Shipped Work

## Summary

Give the Observation Loop an auto-derived manifest of capabilities the pipeline has already shipped, built from merged implementation PRs plus `docs/solutions/`, and feed it into the loop's existing Product Codebase Summary. The loop then stops proposing work that already exists, at the source — no new reject gate. OpenPanel analytics (#762 shipped, #767 redundantly filed) is the acceptance test.

## Problem Frame

The Observation Loop filed wgmesh **#767** "Add web analytics tracking (Plausible/PostHog) to cloudroof.eu landing" on 2026-06-19, while OpenPanel analytics had already shipped via merged PR **#762** (`feat(landing): OpenPanel analytics`) the day before. The redo was not free: #767 advanced into the pipeline and produced open PR **#769**, a Build agent re-implementing analytics that is already live. The same blindness closed #590 ("customer usage analytics") earlier in the same theme.

The loop is not missing a dedup step — it has two, and both failed here. Its issue-creation step does a fuzzy keyword match on issue **titles** only, requiring 2+ keyword hits (`.github/workflows/observation-loop.yml:680-706`); "Add web analytics tracking" and "OpenPanel analytics" share no keywords. Its system prompt instructs the LLM "NEVER create issues for features that already exist," checked against a **Product Codebase Summary** (`company/system-prompt.md:109-113`). But that summary is assembled from the head of the seed repo's `CLAUDE.md` (`.github/workflows/observation-loop.yml:100-105`), and the OpenPanel deployment was never written there. The LLM was told to check a document that did not mention the thing it was about to duplicate.

The cost shape is wasted Build cycles plus operator triage on every redundant issue, recurring for any capability that ships through code but isn't reflected in the loop's grounding.

## Key Decisions

- **Fix the grounding, not the gate.** The remedy is to make the loop *see* what shipped, not to add a stage that rejects duplicate issues after the LLM proposes them. Prevention at the assessment source keeps a single decision point and avoids a second fuzzy-matching surface that would fail the same way the title matcher did.

- **Auto-derive the manifest from merged work.** The capabilities signal is aggregated by a collector from merged implementation PRs and `docs/solutions/` entries each loop run. No hand-maintained file and no live probing of deployed surfaces. This is drift-proof — it cannot fall out of sync with reality because it *is* derived from the record of what shipped.

- **Completeness rests on the pipeline being the only way to ship.** In the autonomous company, every capability reaches production through Issue → Spec → Build → Merge, so every capability leaves a merged-PR trace. The manifest is therefore complete by construction. Hand-deployment would break this, but hand-deployment is itself a constitution violation to fix at its source, not a coverage case this mechanism must absorb.

- **The semantic match is the LLM's job, not new code.** "Add web analytics" and "OpenPanel analytics shipped" do not keyword-match; bridging them is semantic. The design surfaces the capabilities manifest to the LLM richly enough that the model makes the link, rather than adding deterministic matching code that would reproduce the title-matcher's failure.

## Design Rationale (TRIZ/ARIZ)

The contradiction: improve the loop's ability to detect an already-shipped capability (amount of information, detectability) without worsening system and control complexity (a separately-maintained registry that drifts). Matrix 2003 over this contradiction ranks the inventive principles that the chosen approach already embodies:

- **Self-Service (#25)** — *use by-products for useful purposes.* The pipeline's own exhaust — merged implementation PRs — feeds the loop. The capability index is a by-product of shipping, not a new component.
- **Preliminary Action (#10)** — arrange the information in advance so it acts without wasting time. The manifest is pre-computed each run and present at assessment time, ahead of any proposal.
- **Local Quality (#3)** — different parts do different jobs. The merged-PR record carries the recognition data; the LLM does the semantic match. Neither does the other's job (this is why a second deterministic matcher is rejected — it would reproduce the title-matcher's failure).
- **Universality (#6)** — the merged-PR record serves double duty (ship history and capability index), making a separate registry unnecessary.

The Ideal Final Result is the loop knowing shipped state *without the registry existing*; Self-Service realizes it. In resource terms, the **informational resource** (merged PR titles/bodies, `docs/solutions/`) is a hidden resource already in the system — a registry would add a *material* resource and raise complexity. The contradiction dissolves by **separation in time** (derive at run-time, so no persisted state can drift) and **separation between part and whole** (each PR carries its own capability description; there is no maintained whole to keep in sync).

## Requirements

**Capabilities manifest**

- R1. A collector produces a structured manifest of capabilities the pipeline has shipped, derived from merged implementation PRs in the seed repo plus `docs/solutions/` entries.
- R2. The manifest is regenerated each Observation Loop run from current source data, holding no hand-maintained state that could drift from what actually shipped.
- R3. Each manifest entry carries enough description for an LLM to recognize a semantic duplicate of it (the capability's substance, not only an issue title).

**Loop grounding**

- R4. The manifest feeds the Observation Loop's existing Product Codebase Summary, so the LLM sees shipped capabilities during assessment without a new reject stage downstream.
- R5. The grounding surfaces capabilities richly enough that the LLM can link a newly-proposed issue to an existing capability that is worded differently.

**Acceptance proof and cleanup**

- R6. Replaying the conditions that produced #767, with the manifest in place, the loop does not file the redundant analytics issue.
- R7. The live #767 (and its in-flight PR #769) is dispositioned as already-shipped, closed with a reason citing #762.

## Acceptance Examples

- AE1. **Covers R6.** **Given** OpenPanel analytics shipped via merged PR #762 and the capabilities manifest is generated for the loop run, **when** the Observation Loop assesses GTM state and considers proposing web analytics tracking, **then** it recognizes analytics as already shipped and does not add it to `issues_to_create`.
- AE2. **Covers R3, R5.** **Given** a manifest entry derived from #762 whose title says "OpenPanel analytics" and a candidate issue titled "Add web analytics tracking (Plausible/PostHog)," **when** the LLM evaluates the candidate against the manifest, **then** it links the two despite zero shared title keywords and declines the candidate.
- AE3. **Covers R7.** **Given** #767 open and PR #769 in flight, **when** the cleanup runs, **then** #767 is closed with a reason citing #762 as the existing implementation.

## Scope Boundaries

- Live probing of deployed surfaces (e.g. fetching cloudroof.eu to detect the analytics snippet) is rejected — flaky, and per-capability detection code.
- A human-maintained `capabilities.json` is rejected — drift-prone, defeats the zero-maintenance goal.
- A new post-LLM dedup/reject gate is out of scope — the fix lives in grounding, not enforcement.
- Strengthening the existing fuzzy title matcher is not the approach; the manifest plus LLM semantic matching supersedes it for this class.

## Dependencies / Assumptions

- Every shippable capability leaves a merged-PR trace, because the pipeline is the only path to production. The manifest is complete only while this holds; hand-deployment would create an invisible capability and is treated as a violation to fix upstream, not a coverage requirement here.
- Merged implementation PRs carry enough signal in title/body (and `docs/solutions/` enough in content) to describe a capability recognizably. If merged work records capabilities too thinly, R3 weakens — derivation is only as good as what merged work writes down.
- The seed repo is the unit of grounding (currently `atvirokodosprendimai/wgmesh`, resolved as `TARGET_REPO`); cross-repo capability indexing is not assumed.

## Outstanding Questions

*Deferred to planning:*

- The manifest's exact shape, storage location, and the collector script's home in `company/scripts/`.
- How merged-PR derivation handles capabilities later removed or superseded (a shipped-then-reverted capability should not linger in the manifest).
- Whether the grounding augments or replaces the current `CLAUDE.md`-head Product Codebase Summary.
- How the #767/#769 cleanup is triggered — manual disposition now versus the loop's normal reconciliation closing it once the manifest lands.

## Sources / Research

- `.github/workflows/observation-loop.yml:100-105` — Product Codebase Summary built from seed `CLAUDE.md` head.
- `.github/workflows/observation-loop.yml:680-706` — existing fuzzy title-keyword dedup (open + closed issues, 2+ hits).
- `company/system-prompt.md:109-113`, `:136-147` — "NEVER create issues for features that already exist" rule and mandatory reconciliation against the codebase summary.
- `scripts/goal-sprint/fingerprint.sh:40-86` — goal-sprint's fingerprint state file pattern; the Observation Loop has no equivalent "already proposed/shipped" state.
- wgmesh #762 (merged, `feat(landing): OpenPanel analytics`), #767 (open, redundant), #769 (open, redo impl), #590 (closed, prior analytics dup).
