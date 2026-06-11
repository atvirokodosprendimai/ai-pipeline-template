---
date: 2026-06-09
topic: actions-to-langgraph-migration
---

# Retire GitHub Actions — LangGraph Box Owns the Whole Loop

## Summary

Retire the GitHub Actions orchestration and make the existing LangGraph pipeline on the Hetzner box the single owner of the autonomous company: flip it from `spec-only` to `live`, and absorb every job Actions runs today — the convergence chain, the Observation Loop, Self-Heal, Supervisor-Rank, Strategy-Audit, the Pulse, and PR CI — until Actions holds nothing but a single sandboxed CI for untrusted external PRs. Two things stay off the box: that one Actions CI workflow, and a non-Actions dead-man's-switch that alarms when the box goes silent. Cut over strangler-style: prove each box-owned equivalent live, disable (don't delete) its Actions counterpart, empty `.github` last.

---

## Problem Frame

The Actions-based spec→build→merge chain is chronically fragile, and a single issue (#1589) shipped end-to-end this session exposed why: GitHub's workflow-approval gate blocks every `pull_request`-triggered workflow on Copilot-authored PRs (`action_required`, jobs never run) — it blocked spec validation *and* the build-trigger that assigns Goose, so the build never launched. The `bot-pr-review-merge` `*/5` cron is throttled by GitHub to ~every 3 hours. The `PUSH_TOKEN` PAT previously expired and failed 56% of runs in 24h. These are not bugs to fix; they are the structural cost of running an autonomous loop on an event/cron system GitHub never built for it.

The replacement already exists: `pipeline/wgmesh_pipeline` is a LangGraph service on the Hetzner box that runs the full graph (triage → spec → implement → review → gate → merge), built and tested, currently in `spec-only` mode with Actions still live as fallback (per `docs/plans/2026-06-07-001-feat-langgraph-hetzner-pipeline-plan.md`, R8). It owns its own queue, scheduler, and state — no GitHub-side triggers in the loop. This migration is that plan's deferred cutover, taken to its conclusion: everything moves, and Actions goes away.

---

## Key Decisions

- **Total cutover, with two deliberate exceptions.** The box absorbs every orchestration job — Observation Loop, Self-Heal, Supervisor-Rank, Strategy-Audit, Pulse, and PR CI for bot PRs all move onto the box. Two things stay off it: a single retained Actions workflow that runs CI for untrusted external-contributor PRs in GitHub's sandbox (so their code never runs on the secret-bearing box), and the off-box dead-man's-switch below. Maximal autonomy, accepting that the box's blast radius becomes total.
- **This is a cutover, not a rebuild.** The convergence graph, the R5 risk-tier merge gate, the single-PAT identity (KTD3), and the high-risk regexes (KTD4) are inherited from the 2026-06-07 plan and not re-decided here. The `needs-human` ceiling that correctly stopped #1589's payment spec carries over unchanged.
- **Off-box, non-Actions dead-man's-switch.** Box-liveness detection lives on a separate cheap external surface (uptime monitor / second tiny host / serverless ping) — the single external dependency, deliberately *not* on GitHub and *not* on the box. The watcher can't be the watched.
- **Fast reproducible box-rebuild is in scope, not a follow-up.** Total scope makes box death a total outage; the watcher only detects it, so recovery must be a one-command re-provision with state surviving off-box.
- **Strangler cutover, disable-don't-delete.** Each Actions workflow is disabled only after its box-owned equivalent is proven live for a bake period; `.github` is emptied last; rollback at any point is re-enabling the disabled workflow.

---

## Requirements

**Convergence chain → live**
- R1. The pipeline runs in `live` mode: implement → review → gate → merge perform real GitHub writes (branch push, impl PR, merge), not dry-run.
- R2. The R5 risk-tier merge gate is enforced unchanged — low-risk + tests + sanitise + clean review → auto-merge; high-risk paths or any failure → label `needs-human` and stop (see origin: `docs/plans/2026-06-07-001-feat-langgraph-hetzner-pipeline-plan.md`).
- R3. The stranded funnel-instrumentation work (issue #1589; spec `specs/issue-1589-spec.md`, already merged) is built through the live pipeline, not the retired Actions chain.

**Absorbed orchestration**
- R4. The box owns the Observation Loop (decide what to build), Self-Heal (detect and retrigger stalled stages), and Supervisor-Rank (clog ranking), replacing `observation-loop.yml`, `pipeline-health.yml`, `supervisor-rank.yml`.
- R5. The box owns Strategy-Audit and the Pulse, replacing `strategy-audit.yml` and the Actions pulse path; MentisDB thought-chain appends and Langfuse scoring are driven from the box.
- R6. The box runs PR CI — test, lint, sanitise, PII — for the pipeline's own bot-authored PRs, replacing the Actions check workflows. Untrusted external-contributor PRs are CI'd instead by a single retained Actions workflow (GitHub sandbox, no box or secret access); their code never runs on the box.

**Resilience (mandatory for total scope)**
- R7. An off-box, non-Actions liveness monitor alarms when the box goes silent past a threshold; it runs nowhere on the box and is the only external dependency.
- R8. The box is rebuildable from scratch by one command, and pipeline state survives off-box (libsql/Turso), so recovery from box death is fast and unattended-startable.

**Cutover discipline**
- R9. Cut over strangler-style: an Actions workflow is disabled (not deleted) only after its box-owned equivalent is proven live for a bake period; `.github/workflows/` is reduced to the single external-PR-CI workflow last; rollback is re-enabling a disabled workflow.
- R10. No GitHub-side workflow triggers remain in the loop — the box owns its queue, scheduler, and state; nothing depends on Actions cron, label-trigger, or `pull_request` events.

**Boundary**
- R11. The public-repo boundary holds: no secrets, PII, or exact revenue committed; secrets live on the box and in the off-box monitor's config, never in the repo.

---

## Key Flows

- F1. Live convergence (issue → merged code)
  - **Trigger:** The box polls a `fn:dev` issue.
  - **Steps:** triage → spec (Goose) → implement (Goose) → review → risk-tier gate → auto-merge (low-risk, green) OR label `needs-human` and stop (high-risk path or any failure).
  - **Covers:** R1, R2

- F2. Box-death detection and recovery
  - **Trigger:** The box goes silent (crash, provider outage, hung loop).
  - **Steps:** the off-box watcher passes its threshold and alarms; an operator runs the one-command re-provision; the box restarts and resumes from off-box state.
  - **Covers:** R7, R8

- F3. Strangler cutover per subsystem
  - **Trigger:** A box-owned equivalent of an Actions workflow is ready.
  - **Steps:** run the box equivalent in parallel with the Actions workflow through a bake period; once proven, disable the Actions workflow (keep the file); when all subsystems are cut over, empty `.github/workflows/`.
  - **Covers:** R9

---

## Scope Boundaries

**Deferred for later**
- Box HA / a second box / redundancy — this migration adds *detection* (R7) and *fast rebuild* (R8), not prevention. True redundancy is a separate resilience effort.
- Re-architecting the convergence graph or the risk-tier gate logic — inherited from the 2026-06-07 plan, not reopened here.

**Outside this product's identity**
- This moves the execution substrate; it does not change what the company builds (wgmesh) or the autonomous-convergence thesis. Not a product redefinition.

---

## Dependencies / Assumptions

- The LangGraph convergence graph (triage → spec → implement → review → gate) is built and tested — verified: `pipeline/wgmesh_pipeline` with `test_implement_retry_pr.py`, `test_build_escalation.py`, `test_gate.py`. Only `live`-mode writes, deployment, and cutover remain (the 2026-06-07 plan's deferred phases).
- PR CI on the box covers the pipeline's own bot-authored PRs. Untrusted external-contributor PRs (public repo) are assumed rare and handled manually — running untrusted PR code on a secret-bearing box is out of scope (see Outstanding Questions).
- The off-box monitor adds a small recurring cost or uses a free tier — needs frugality approval (human approves recurring spend > 0).
- Langfuse is already self-hosted; MentisDB is reachable from the box.
- A single fine-grained PAT identity on the box (issues / contents / pull_requests); self-merge is permitted, self-approval-review is not depended on (KTD3, 2026-06-07 plan).

---

## Outstanding Questions

**Resolve before planning**
- None. The external/untrusted-PR-CI security boundary is resolved: a single retained Actions workflow runs CI for external PRs in GitHub's sandbox, never on the box (R6).

**Deferred to planning**
- Which off-box monitor surface (uptime SaaS free tier vs second tiny host vs serverless ping).
- The bake-period length per subsystem before disabling its Actions counterpart.
- Whether the Observation Loop's "what to build" decisioning moves wholesale or is re-derived natively on the box.
- Order of subsystem cutover (convergence-to-live first is the obvious lead; the rest is planning).

---

## Sources / Research

- `docs/plans/2026-06-07-001-feat-langgraph-hetzner-pipeline-plan.md` — the LangGraph pipeline plan; this migration is its deferred cutover. Carries R3 (graph), R5 (gate), R7 (shadow), R8 (Actions-as-fallback), KTD3 (single PAT), KTD4 (risk tiers), KTD7 (`PIPELINE_MODE`).
- `pipeline/wgmesh_pipeline/` — `poller.py` (stage advancement + mode handling), `models.py`, `gate`/`implement`/`review` nodes; the `pipeline/tests/` suite confirms the graph is built and tested.
- `.github/workflows/` — the orchestration layer being retired: `copilot-triage`, `spec-validation`, `spec-merged-build`, `bot-pr-review-merge`, `heartbeat-pr-automerge`, `approve-build`, `pipeline-health`, `supervisor-rank`, `strategy-audit`, `observation-loop`, `checkout-monitor`, plus the sanitise/PII checks.
- Session evidence (2026-06-09, issue #1589): the Actions workflow-approval gate blocked spec validation and the Goose build-trigger (jobs never ran); `bot-pr-review-merge` `*/5` throttled to ~3h; the `needs-human` payment ceiling correctly held. The motivating failure set.
- `STRATEGY.md` — the "no babysitting" autonomy thesis the migration serves by removing the Actions fragility class.
