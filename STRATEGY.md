---
name: ai-pipeline-template
last_updated: 2026-05-06
---

# ai-pipeline-template Strategy

## Target problem

A solo founder with a vertical idea has a clear product goal, but existing AI-agent pipelines need babysitting and don't converge fast enough on it. Taste and idea don't translate into a shipped product, so the runway burns before revenue arrives.

## Our approach

Bet on actually converging autonomously from seed to shipped product, where autonomous-coding competitors plateau at code generation that still needs human babysitting. The pipeline commits to producing finished, deployed products without a human in the loop.

## Who it's for

**Primary:** Pre-revenue side-projecting technical solo founder with deep vertical expertise — they read code, debug agent output, and own the vertical taste. They're hiring ai-pipeline-template to convert their vertical-expert side project into first revenue without writing or integrating every glue line by hand.

## Key metrics

> **Important — product vs. meta.** "Convergence" is measured in the SEEDED PRODUCT repo (currently `atvirokodosprendimai/wgmesh`), not in `ai-pipeline-template`. PRs in `ai-pipeline-template` are pipeline self-maintenance (`heal:`, `loop:`, process gates) and do not count as product convergence. Filter every PR-flow metric by title prefix (`spec:`, `impl:`) AND repo (`atvirokodosprendimai/wgmesh`). The 2026-05-06 pulse caught this: a 100% "autonomous-ship rate" can be true while zero product PRs ship. Don't conflate the two surfaces.

- **Paid customers** — count of subscribers paying for any seeded product. Source: Polar/Stripe. Lagging.
- **Goose autonomous-ship rate** — % of `impl: Issue #N` PRs in the seeded product repo (currently wgmesh) that merge with zero `## Escalated to Human Review` comments and zero `awaiting-tests`/`awaiting-verification` reopen events. (`awaiting-tests` and `awaiting-verification` are labels defined and managed by wgmesh's `.github/workflows/impl-merged-close.yml` test-gate workflow — not labels in this meta-pipeline repo's label set.) Source: `gh pr list --repo <seed-repo> --search "is:merged impl: in:title"` + comment/label scan. Leading.
- **Lead time spec → merge** — median hours from `spec: Issue #N` PR opened to corresponding `impl: Issue #N` PR merged in the seeded product repo. Skips meta-pipeline work. Source: GitHub PR data on the seed repo. Leading.
- **Spec coverage** — for issues opened in the seeded product repo, the fraction with at least one `spec: Issue #N` PR (open or merged). Surfaces issues stuck in `copilot-triaging` because no spec was written. Leading.
- **Self-heal resolution rate** — `actions_taken / (actions_taken + needs_human_closed)` — fraction healed without escalation. Source: `company/pipeline-health-state.json`. Leading.
- **Active stuck issues** — open issues in the seeded product repo at `needs-human` OR in `copilot-triaging` >24h OR in retry cooldown >24h. Source: `gh issue list`. Leading.
- **Cycle time to revenue** — median hours from first commit on a seed product → that seed's first paying customer event. Source: git log + Polar/Stripe webhook timestamps. Lagging — `null` until ≥1 customer exists. Tempo-anchor: target ≤72h.

## Tracks

### Convergence engine

Agent loop that drives a seed through triage → spec → impl → merge → deploy. Covers Goose, copilot-triage, copilot-undraft, spec-merged-build, approve-build.

_Why it serves the approach:_ this is the mechanism by which the pipeline produces a finished product autonomously. Owns autonomous-ship rate and lead time.

### Self-heal & resilience

pipeline-health workflow, audit log, retry/cooldown tracker, circuit breaker, escalation to needs-human.

_Why it serves the approach:_ "no babysitting" is only real if the pipeline detects, retries, and recovers without a human watching. Owns self-heal rate and active stuck issues.

### Customer Factory / Revenue surface

cloudroof.eu (seed entry + landing), chimney.beerpub.dev (KPI dashboard), Polar tiers, distribution glue. The path from shipped product → euro on the bank account.

_Why it serves the approach:_ converging on code without converging on revenue is theatre. Owns paid customers.

## Milestones

- **2026-05-10** — first audit-loop closes cleanly (drift PR opens, founder applies, doc updates, audit re-runs green)
- **2026-05-17** — wgmesh edge node beta (first seeded product reaches public beta)
- **2026-05-31** — 1 paying customer
- **2026-06-14** — 2nd seed product spec'd and entering convergence engine
- **2026-08-31** — 4 customers ($10K ARR run-rate path)
- **2027-05-03** — 42 customers, $10K ARR
- **2028-05-03** — 420 customers, $100K ARR (MSC)

## Not working on

- Anything that can wait until $10K ARR is hit.

## Marketing

**One-liner:** Measuring outcomes, not outputs.
