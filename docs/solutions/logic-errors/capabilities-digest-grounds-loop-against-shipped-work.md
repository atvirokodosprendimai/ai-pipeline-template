---
title: "Capabilities digest grounds the observation loop against re-proposing shipped work"
category: logic-errors
date: 2026-06-19
tags: [observation-loop, llm, dedup, codebase-awareness, capabilities, grounding]
related_issues:
  - https://github.com/atvirokodosprendimai/wgmesh/issues/767
  - https://github.com/atvirokodosprendimai/wgmesh/pull/769
  - https://github.com/atvirokodosprendimai/wgmesh/pull/762
severity: high
component: observation-loop
---

# Capabilities digest grounds the observation loop against re-proposing shipped work

## Problem

The Observation Loop filed wgmesh #767 "Add web analytics tracking (Plausible/PostHog)"
while OpenPanel analytics had already shipped one day earlier via merged PR #762
(`feat(landing): OpenPanel analytics`). The redundant issue advanced into the pipeline and
produced open PR #769 — a Build agent re-implementing analytics that is already live.

Both existing dedup mechanisms missed it:

- The issue-creation step's fuzzy keyword match runs on issue **titles** only
  (`.github/workflows/observation-loop.yml:688-705`). "Add web analytics tracking" and
  "OpenPanel analytics" share no title keywords.
- The system prompt's "do not duplicate" rule checks a **Product Codebase Summary** built
  only from the head of the seed repo's `CLAUDE.md` (`observation-loop.yml:88-105`). The
  OpenPanel deployment was never written there, so the LLM had no grounding for it.

The capability shipped through a merged PR — invisible to issue-title dedup and absent from
the grounding the LLM reads.

## Root cause

This is the same failure class as
[observation-loop-creates-bogus-issues-for-existing-features](./observation-loop-creates-bogus-issues-for-existing-features.md)
(the loop filing #453/#458/#460 for shipped features), whose fix created the Product
Codebase Summary. The carry-forward rule from that RCA holds here: *a single corrective
signal cannot override compounding LLM priors, and metadata alone is insufficient — the LLM
needs structural/capability awareness.* The Product Codebase Summary delivered that awareness
only for what is documented in `CLAUDE.md`; a capability shipped via PR but not written into
`CLAUDE.md` stayed invisible.

## Fix

Generalize the Product Codebase Summary into an auto-derived **capabilities digest**, fed
into the loop's grounding at the assessment source — not a new dedup gate.

- `company/scripts/collect-capabilities.sh` derives a plain-text digest from recent merged
  implementation PRs (`gh pr list --state merged --limit N --json number,title,body`) plus
  `docs/solutions/` entries. Newest-first, deduped, budget-bounded by whole lines.
- Reverted capabilities are reconciled out: a `Revert "<title>"` PR subtracts the matching
  capability so the digest never asserts a removed capability is shipped.
- The observation loop runs the collector each tick (best-effort, `GH_TOKEN` + `TARGET_REPO`
  env) and surfaces it as a dedicated `## Already-Shipped Capabilities` block in the
  assessment prompt — distinct from the CLAUDE.md-head summary so provenance stays honest
  and the block is not buried among priors.
- The system prompt's no-duplicate rule and mandatory reconciliation pass both reference the
  new block.

Reads PRs deliberately via `gh pr list`, never `gh issue list` — the `/issues` API also
returns PRs (`pull_request` key), and a digest built from "issues" would ingest the loop's
own spec PRs and runaway.

## Why it works (and the load-bearing bet)

The match between a differently-worded proposed issue ("add web analytics") and a shipped
capability ("OpenPanel analytics") is **semantic, not lexical** — no keyword code bridges it.
The design surfaces capabilities richly into grounding and leaves the match to the LLM,
rather than adding deterministic matching that would reproduce the title-matcher's miss. This
is the load-bearing bet: the model reads the block and declines the duplicate.

That bet is verified by a **control replay**, not a single observation: run the #767-condition
assessment twice — once with the digest populated (expect: analytics not proposed) and once
with it empty (expect: analytics proposed). A single non-occurrence cannot distinguish "the
digest works" from "the loop happened not to re-file"; the two-arm control can.

## Status

- Collector, loop wiring, and system-prompt grounding: shipped (PR #1849, `2aecc34` on main).
  Takes effect on the next Observation Loop run — the loop is a GitHub Actions cron
  (`observation-loop.yml`, `runs-on: ubuntu-latest`), not the Hetzner box; no deploy needed.
- **Control replay, deterministic arm — PASS (2026-06-19).** `collect-capabilities.sh` run live
  against `atvirokodosprendimai/wgmesh` (`--limit 200`) surfaced the OpenPanel capability with
  rich body context: `OpenPanel analytics — track Polar CTA clicks (PR #762) — Adds the OpenPanel
  tracker (self-hosted at counter.hackrsvalv.com) to the 4 landing pages...` (34 capability lines,
  clean run). The grounding the LLM needs to make the #767 match is present and well-formed.
- **Control replay, semantic arm — pending.** The two-arm LLM call (digest present → analytics not
  proposed; digest empty → proposed) requires the loop model (`anthropic/claude-sonnet-4` via
  OpenRouter, `OBSERVER_API_KEY`) and spends metered budget; run via a dispatch-only replay or
  the next live tick observed against the control. Record the two arms here when run.
- Disposition of the live #767 / #769: pending operator authorization (public seed repo).

## Residual risks

- **Non-`Revert` supersession.** A capability rewritten or removed by a PR that does not use a
  `Revert "<title>"` title is not reconciled out, and could suppress legitimate re-work. Only
  `Revert`-titled removals are handled today.
- **Recency window.** The digest is bounded to recent merged PRs; capabilities older than the
  window rely on the existing CLAUDE.md-head Product Codebase Summary as the long-tail backstop.
- **Grounding dilution at scale.** A long digest among priors can lose attention; the recency
  bound and the dedicated block mitigate this, and a candidate-relevant scoping pass is the
  fallback if dilution recurs.
