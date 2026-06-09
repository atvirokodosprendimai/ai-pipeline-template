---
date: 2026-06-09
topic: open-ideation
focus: (open-ended / surprise-me)
mode: repo-grounded
---

# Ideation: Autonomous Pipeline — Open Surprise-Me Run

## Grounding Context (Codebase Context)

`ai-pipeline-template` is the control plane for an autonomous AI software company: zero product code, pure orchestration (GitHub Actions crons, bash, LLM system prompts, state machines, a LangGraph pipeline on Hetzner + self-hosted Langfuse). It builds/ships the seed product **wgmesh** (Go decentralized WireGuard mesh, Dogfood stage, 18 stars) and is chasing revenue (cloudroof.eu, Stage 5 "Revenue", Day 83, **0 verified paying customers**).

Current state (2026-06-09 pulse):
- **Convergence-at-merge = 0**: 8 wgmesh specs opened today (first spec motion in 80+ days) but 0 product code merged. Bottleneck moved from "no specs" to "specs not converging to merged code."
- Revenue metrics stale since April (`metrics.json` Apr 11, `costs.json` Apr 10); "0 customers" carried forward unverified; no Polar access; Polar possibly misconfigured (5 org subs vs 0 cloudroof, flagged May 26).
- Self-heal was dead 6 days (777 checks/0 healed, malformed `gh --jq` swallowed by `|| true`); recovered, now 812 checks/17 healed.
- Provision Pipeline Box is a single point of failure (failed once @04:52).
- #736 (needs-human) and #753 (spec) aged 34 days. Supervisor-rank at run #10.

Hard-won learnings: real-artifact LLMs need ground-truth code context not metadata; stale state amplifies hallucination; verify-by-LANDING not by unit test (5 LangGraph bugs each passed 98 tests); `|| true`/`except: pass` hide dead automation; review/verification (not generation) is the industry bottleneck; LLM-judges are gameable; revenue/customer side has ~0 institutional learnings.

## Topic Axes

Decomposition skipped — surprise-me mode.

## Ranked Ideas

### 1. Convergence accounting: death-ledger + stop-the-line WIP limit + per-spec kill criteria
**Description:** Instrument where each spec dies (queryable failure distribution, not "0 merged"); freeze new spec/issue generation when merge-convergence stays 0 for N cycles (Toyota Andon); give each spec a pre-declared "definition of dead" enforced by the clog-ranker so zombies die fast instead of aging 34 days.
**Basis:** `direct:` pulse "convergence at merge is still 0," #736/#753 aged 34d. `external:` Toyota jidoka/Andon, pharma pre-registered kill criteria.
**Rationale:** Can't fix convergence you can't see; flooding a clogged merge stage with 8 more specs is motion mistaken for progress.
**Downsides:** WIP freeze can read as the pipeline idling; needs a good N and a clear swarm target.
**Confidence:** 88% **Complexity:** Medium **Status:** Unexplored

### 2. Evidence-gated spec stage: executable acceptance test + isomorphic ground-truth check
**Description:** Replace the prose spec (and its human review gate) with a failing acceptance test as the build contract; gate spec→build by re-deriving claimed files/symbols from the real codebase and rejecting hallucinated references. Human reviews a green landed diff, not a prediction.
**Basis:** `direct:` "5 bugs each passed 98 unit tests — verify-by-LANDING," wgmesh#458 ground-truth-context learning, #753 aged at the human gate. `external:` review is THE 2026 bottleneck; judges gameable → pair with verifiable/isomorphic checks.
**Rationale:** A prose spec is a prediction; a red→green test is both spec and verification, collapsing the lossy handoff that yields 0 converged code.
**Downsides:** Not every issue reduces to one acceptance test; isomorphic check needs reliable symbol extraction.
**Confidence:** 80% **Complexity:** Medium-High **Status:** Unexplored

### 3. Metrics freshness contract + action-halting circuit breaker
**Description:** Single append-only metrics ledger with a per-field TTL — stale renders `UNKNOWN` everywhere it's consumed, never carried forward; a daily revenue sentinel that ANNOUNCES on silence and opens a `fn:billing` P0; a circuit breaker that lets the loop observe but not act on stale state.
**Basis:** `direct:` metrics/costs ~2mo stale, "0 customers carried forward unverified," Polar misconfig open since May 26; "stale state amplifies hallucination." `external:` epidemiology sentinel surveillance, market circuit-breakers.
**Rationale:** The one stuck metric (revenue) is the least-instrumented surface; carrying a stale "0" forward is the metrics version of `|| true`.
**Downsides:** Too-tight breaker could stall the loop; doesn't itself fix Polar — makes the blindness loud.
**Confidence:** 86% **Complexity:** Medium **Status:** Unexplored

### 4. Silent-degradation registry (aviation MEL)
**Description:** A registry of every critical component (heal mutations, Box liveness, last product merge) with a declared max-silent-duration; breach is a loud event that can ground deploys. Seed it with a one-time `|| true`/`except: pass`/`2>/dev/null` sweep of the control plane.
**Basis:** `direct:` self-heal dead 6 days behind a swallowed `gh --jq`; Box SPOF failed @04:52 — both caught only via a human reading the pulse. `external:` FAA Minimum Equipment List, ecology keystone monitoring.
**Rationale:** The two worst recent incidents share a root that isn't the bug — it's detection latency; make max-silence a tracked, deadline-bearing number.
**Downsides:** Alarm-fatigue risk if thresholds are wrong; "ground deploys on staleness" needs care not to self-DoS.
**Confidence:** 85% **Complexity:** Medium **Status:** Unexplored

### 5. Self-feeding eval corpus: every failure auto-enrolls as a permanent trajectory/regression eval
**Description:** A one-way valve on the Langfuse layer: any judge/human/CI-flagged trace (+ the 5 known LangGraph bugs, + stuck specs) auto-promotes into a versioned regression dataset every future change is scored against. Cheap judge on 100% of traces; expensive judge + human sample only on anomalies.
**Basis:** `direct:` "evals gate-only (no trajectory evals, no regression corpus from the 5 real bugs — a free dataset sitting unused)." `external:` continuous prod eval > pre-deploy gate; trace→dataset is the mature Langfuse layer.
**Rationale:** Purest compounding asset available — a dataset that grows in value every time something breaks, turning each failure into permanent immunity.
**Downsides:** Noisy auto-enrollment needs dedup and a relevance-decay policy.
**Confidence:** 82% **Complexity:** Medium **Status:** Unexplored

### 6. Reversibility-gated autonomy: the human ceiling gates one-way doors, not content category
**Description:** Flip the human gate from content-sensitivity to reversibility. A disposition agent auto-merges anything reversible and physically cannot approve irreversible/external actions (prod deploy, Polar/billing change, customer email, Terraform destroy), which hard-route to the human. Frame "human touches only the ~5% irreversible" as a feature.
**Basis:** `external:` 2026 sandwich control (rails floor + agent middle + human ceiling on irreversible actions), "your agent may misevolve." `direct:` system-prompt already defines `needs_human` as "no reversible path"; #736 sat 34d at a gate that may not have needed to be one.
**Rationale:** Human review is the binding constraint; safely removing the maintainer from the easy 80% requires partitioning reversible vs irreversible and making them the ceiling, not the funnel.
**Downsides:** Reversibility classification is itself a judgment with failure modes; mis-classifying irreversible-as-reversible is the dangerous error — needs a conservative default.
**Confidence:** 78% **Complexity:** Medium-High **Status:** Unexplored

### 7. Validate demand & the billing path before perfecting throughput
**Description:** Two cheap probes for the company's most-absent data (revenue learnings ≈ 0). (a) A synthetic end-to-end paid-transaction test — drive a real signup→checkout→invoice against cloudroof + Polar in a sandbox to prove a customer *can even pay us* before a real lead arrives (directly tests the suspected Polar misconfig). (b) A demand probe — reframe the 2026-06-14 "2nd seed spec'd" milestone as *demand-tested* (waitlist/paid-landing-first), funded by a tiny pre-approved "evidence budget" carved out of the frugality rule. **Phase 2 (gated behind a provably-working checkout): a distribution arm for the `fn:gtm` lane.** [Mixpost](https://mixpost.app/) — self-hosted, open-source, one-time-payment, API-driven social media scheduling/publishing across 11 platforms — is a strong fit as the autonomous content megaphone, but it is a *distribution* tool, not a *validation* instrument: its analytics are engagement/follower-level, not conversion/willingness-to-pay. It amplifies the top of the funnel and must not precede a working capture (waitlist) + checkout (Polar) + conversion-attribution (PostHog) path, or it pours traffic into a funnel that can't convert and adds another service to a single-point-of-failure infra.
**Basis:** `direct:` Day-83/Stage-5/0 verified customers; Polar misconfig (5 org subs vs 0 cloudroof); revenue side has ~0 institutional learnings; system-prompt frugality ladder; server-side PostHog already instrumented. `external:` Gartner — 40% of agentic projects canceled by 2027; convergence-throughput is vanity if the output has no buyer; Mixpost capabilities verified via mixpost.app.
**Rationale:** Optimizing spec→merge when the output may have no buyer (and billing may be broken) is local-optimum theatre; the cheapest path to the missing customer-side data is a synthetic transaction + a demand probe, with distribution amplification gated behind a working checkout.
**Downsides:** Strategy-altitude — partly a founder decision, not pure pipeline work; "is there a buyer" can't be fully answered by the pipeline alone.
**Confidence:** 75% **Complexity:** Low-Medium **Status:** Explored

## Rejection Summary

| # | Idea | Reason Rejected / Disposition |
|---|------|-------------------------------|
| 1 | Friction-weighted clog ranking (F1#4) | Folded → #1 (kill criteria / accrued-wait weighting) |
| 2 | Reproducible NAT-sim harness (F1#6) | Near-miss — strong + grounded, but narrow to wgmesh networking; deserves its own verify-by-landing track |
| 3 | Land-first / zero-spec / executable test (F2#1,#4; F6#6) | Folded → #2 |
| 4 | Sandwich auto-disposer / human-ceiling-as-feature (F2#3, F3#6) | Folded → #6 |
| 5 | Customer-truth probe (F2#5) | Folded → #3 (sentinel) |
| 6 | Stage = lowest unsatisfied exit criterion (F3#1) | Folded → #3/#4 (ground-truth freshness) |
| 7 | Decouple assess from decide (F3#7) | Folded → #3 (circuit breaker; facts vs narrative) |
| 8 | Deployed-and-used as the convergence terminal (F3#5) | Folded → #5 (anchor scoring to real use; anti-gaming) |
| 9 | Convergence corpus replay harness (F4#1) | Folded → #1 (ledger) + #5 (corpus) |
| 10 | Reconciliation-as-a-service (F4#5) | Near-miss — good, but overlaps in-flight reconciliation work |
| 11 | Spec contract linter (F4#6) | Folded → #2 (isomorphic check) |
| 12 | Provision Box: self-reprovision / keystone / embrace-SPOF (F2#6, F4#4, F5#6, F6#7) | Folded → #4; recovery-automation is a near-miss follow-on |
| 13 | Hospital-triage acuity / €0 path / continuous cheap judge (F5#2, F6#1, F4#7) | Folded → #5/#6 (budget by blast-radius) |
| 14 | Carrier wave-off default-abort deploy (F5#5) | Folded → #4 (ground-the-flight on ambiguity) |
| 15 | 10x-budget thought experiment (F6#5) | Rejected — framing exercise, not an actionable product change |
| 16 | Human-on-every-step calibration week (F6#2) | Rejected — too disruptive relative to value now; partial idea lives in #5 |
| 17 | Team-of-1 agent (F6#4) | Rejected — large architectural bet that contradicts the just-built multi-agent LangGraph |
