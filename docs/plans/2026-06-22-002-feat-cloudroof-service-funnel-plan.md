# feat: Cloudroof service funnel — 2nd pipeline instance for cloudroof-eu

**Date:** 2026-06-22 · **Type:** feat · **Depth:** Deep
**Origin:** `docs/brainstorms/2026-06-22-cloudroof-service-funnel-requirements.md`
**Grounding:** `/tmp/compound-engineering/ce-plan/cloudroof-funnel/grounding.md`

---

## Summary

Stand up a SECOND `wgmesh_pipeline` instance on the existing box targeting `cloudroof-eu`,
so service code issues (already emitted there by the observation loop) get built → PR'd →
merged → deployed to the Cloudflare Workers site. Reuses all machinery; the only new code is
infra (2nd systemd unit + env + provision parameterization), the cloudroof instance's surface
gate inversion, cloudroof-eu's missing CI (impl-judge) + wrangler deploy CD, and a
Quackback-gated accept step.

## Problem frame

The product/service split shipped the gate (surface-gate holds `surface:service` out of the
wgmesh builder) and the routing (`observation.py` `SURFACE_REPO` already emits service issues
to cloudroof-eu), but never the service BUILDER. Service issues land in cloudroof-eu with
nothing polling/building them → 0 product convergence ~4 pulses while wgmesh's backlog is
exhausted. This funnel is the company's gating constraint.

## Key technical decisions

- **KTD1 — 2nd instance, not a multi-repo refactor.** A separate `cloudroof-pipeline.service`
  systemd unit runs the same `wgmesh_pipeline.main` with its own `EnvironmentFile`, DB path,
  and checkout. Env delta is 5 vars (`TARGET_REPO`, `WGMESH_CHECKOUT_PATH`, `PIPELINE_DB_PATH`,
  `WGMESH_BOT_PAT` scoped to cloudroof-eu, optional `LANGFUSE_*`). No core code change — the
  pipeline is already `Config.target_repo`-driven (see origin).
- **KTD2 — surface gate inverts per instance.** The wgmesh instance keeps blocking `service`;
  the cloudroof instance must PASS `service` (and block `product`/`unknown`). Drive this off
  `Config.target_repo` (or a `SURFACE_HOME` config) so one codebase serves both. Routing into
  cloudroof-eu already works (`observation.py` `SURFACE_REPO`); only the builder-entry gate
  changes.
- **KTD3 — Workers deploy stays in cloudroof-eu Actions, not the box.** The box produces code +
  merges PRs; `wrangler deploy` runs as a cloudroof-eu CD workflow on merge to main (CD = the
  one thing that stays in Actions, per the Actions=CI/CD-only principle). cloudroof-eu already
  has `wrangler.jsonc` (`name: creu`, assets `./dist`).
- **KTD4 — accept-gate via Quackback gtm-stream (operator decision), which couples to the
  Quackback cutover.** The gated-first-N phase reads "Accepted for Build" from the Quackback
  gtm-decision stream. Quackback is not yet live (forge still github), so the gate unit (U6) is
  sequenced AFTER the Quackback cutover. The build+deploy chain (U1–U5) ships independently and
  proves end-to-end; until the gate lands the funnel runs manually-triggered / limited, NOT
  open auto-build (avoids spending effort + brand risk on unvetted service features).
- **KTD5 — impl-judge is repo-agnostic; selfheal is config-driven.** cloudroof-eu just needs
  its own `impl-judge.yml` (copy from wgmesh + `OPENROUTER_API_KEY` secret + required check).
  merge-lane-heal (`selfheal/merge_lane.py`) derives target from `Config.target_repo`, so the
  cloudroof instance heals cloudroof-eu automatically — no change.

---

## High-level technical design

```
goal-sprint / observation loop (wgmesh instance)
   └─ surface:service issue ──(SURFACE_REPO, already wired)──▶ cloudroof-eu issue
                                                                      │
                          ┌───────────────────────────────────────────┘
                          ▼
   cloudroof-pipeline.service  (2nd instance, TARGET_REPO=cloudroof-eu, own env/db/checkout)
     poller.tick → surface_gate (PASS service) → [U6: Quackback accept-gate, first N]
        → spec → impl → PR  (cloudroof-eu CI: ci.yml build + impl-judge required)
        → judge-gated auto-merge → merge to main
                                       │
                                       ▼
                cloudroof-eu Actions: wrangler deploy ./dist ▶ cloudroof.eu  (CD stays in Actions)
```

---

## Implementation units

### U1. cloudroof-eu CI: impl-judge + build gate
**Goal:** cloudroof-eu PRs get the same gating wgmesh has so judge-gated auto-merge works.
**Requirements:** Outcome (autonomous build), KTD5. **Dependencies:** none. **Target repo:** cloudroof-eu.
**Files:** (in cloudroof-eu) `.github/workflows/impl-judge.yml` (copy from wgmesh), `.github/workflows/ci.yml` (JS/wrangler: `npm ci` + build/typecheck + `wrangler deploy --dry-run`), repo ruleset/required-checks.
**Approach:** Port wgmesh `impl-judge.yml` verbatim (it's repo-agnostic — reads the PR diff); add `OPENROUTER_API_KEY` as a cloudroof-eu secret. Add a secretless `ci.yml` mirroring wgmesh's all-authors build gate but for the JS/Workers stack (build `./dist`, wrangler dry-run validates config). Set impl-judge + ci as required checks on cloudroof-eu's protect-main ruleset.
**Patterns to follow:** wgmesh `.github/workflows/impl-judge.yml`, `ci.yml`; the ruleset script `scripts/ruleset/apply-required-checks.sh`.
**Test scenarios:** workflow YAML validates; impl-judge runs on a sample cloudroof bot PR and posts a check; ci build passes on a clean PR and fails on a broken build. `Covers AE: one service code issue builds to a merged PR.`

### U2. cloudroof-eu wrangler deploy-on-merge (CD)
**Goal:** a merged cloudroof-eu PR auto-deploys to cloudroof.eu.
**Requirements:** Outcome (live deploy), KTD3. **Dependencies:** none. **Target repo:** cloudroof-eu.
**Files:** (in cloudroof-eu) `.github/workflows/deploy.yml` (on push to main → build `./dist` → `wrangler deploy`).
**Approach:** `workflow_run`/`push:main` triggered; needs `CLOUDFLARE_API_TOKEN` (+ account id) secret on cloudroof-eu. Deploy only on green main. Concurrency cancel-in-progress. This is CD, stays in Actions (KTD3).
**Patterns to follow:** wgmesh `auto-deploy-on-merge.yml` (the merge→deploy chain shape), cloudroof-eu existing `spec-merged-build.yml`.
**Test scenarios:** dry-run deploy succeeds with the token; a merge to main triggers deploy and the site serves the new asset; deploy on red main does not fire. `Covers AE: built feature goes live end-to-end.`

### U3. Surface-gate inversion for the service instance
**Goal:** the cloudroof instance builds `service` issues; the wgmesh instance still blocks them.
**Requirements:** KTD2, F (intake). **Dependencies:** none.
**Files:** `pipeline/wgmesh_pipeline/graph/nodes/surface_gate.py`, `pipeline/wgmesh_pipeline/config.py`, `pipeline/tests/test_surface_gate.py`.
**Approach:** Add a `Config.surface_home` (or reuse `target_repo` mapping) = which surface this instance builds (`product` for wgmesh, `service` for cloudroof). `decide_surface_gate` passes when `issue.surface == config.surface_home`, blocks otherwise (incl `unknown`). Default `product` (wgmesh unchanged). The cloudroof instance sets `service`.
**Patterns to follow:** existing `surface_gate.py` `decide_surface_gate`, `observation.py` `_resolve_surface`/`SURFACE_REPO`.
**Test scenarios:** `surface_home=service` → service issue PASSES, product BLOCKED, unknown BLOCKED; `surface_home=product` (default) → unchanged from today (service blocked); both graph impls (legacy + langgraph) honor it. Edge: missing surface → block. `Covers F: intake routes code-service to the funnel.`

### U4. 2nd pipeline instance — systemd unit, env, provision parameterization
**Goal:** the box runs a `cloudroof-pipeline` process with isolated state.
**Requirements:** KTD1, constraint (2 processes/1 box). **Dependencies:** U3 (so the instance gates correctly).
**Files:** `pipeline/deploy/cloudroof-pipeline.service`, `.github/workflows/provision-pipeline-box.yml`, `.github/workflows/update-pipeline-box.yml`, `.github/workflows/set-box-env.yml` (add a `service` input: `wgmesh|cloudroof` → resolves unit name + `ENV_FILE` path), `pipeline/wgmesh_pipeline/config.py` (surface_home + SURFACE_HOME env in box-config allowlist).
**Approach:** New unit mirrors `wgmesh-pipeline.service` with `EnvironmentFile=/etc/cloudroof-pipeline/env`, `WorkingDirectory=/opt/cloudroof-checkout`. Parameterize the 3 box workflows with a `service` input (default wgmesh = unchanged) that picks unit + env-file path. The cloudroof env sets the 5 delta vars + `SURFACE_HOME=service` + `CONTROL_LOOP_ENABLED=true`. Use the env-file PARSE-not-source path (the [[feedback_box_env_not_bash_sourceable]] fix already landed).
**Execution note:** characterization-first on the 3 box workflows — they're load-bearing infra; assert the wgmesh path is byte-unchanged when `service` defaults.
**Test scenarios:** set-box-env with `service=cloudroof` writes `/etc/cloudroof-pipeline/env` + restarts `cloudroof-pipeline`; `service=wgmesh` (default) unchanged; YAML valid; unit file parses. Test expectation: workflow logic via characterization + YAML lint (no app behavior).

### U5. Provision live + end-to-end smoke (MVP proof)
**Goal:** one real cloudroof-eu issue → spec → impl → PR → merge → deployed, no hand edits.
**Requirements:** Outcome. **Dependencies:** U1, U2, U3, U4.
**Files:** none (operational); runbook `docs/runbooks/cloudroof-funnel-cutover.md`.
**Approach:** Verify box capacity for a 2nd process (`cpx22` headroom — if thin, size up the VM; record decision). Mint a fine-grained `WGMESH_BOT_PAT` scoped to cloudroof-eu (read+write). Set cloudroof-eu secrets (OPENROUTER_API_KEY, CLOUDFLARE_API_TOKEN). Provision the 2nd instance. Pick one existing cloudroof-eu issue (e.g. the rerouted onboarding widget #4), run it through, confirm deploy. Run the cloudroof instance in shadow first (like the merge-lane cutover), then live.
**Execution note:** shadow-prove (poller shadow / one cycle logged) before flipping live, mirroring the merge-lane-heal cutover discipline.
**Test scenarios:** Test expectation: none — operational verification (the runbook's checklist + the live smoke is the proof). Verification: a cloudroof-eu PR opened by the instance, judge-gated, merged, site updated.

### U6. Quackback accept-gate (gated-first-N) — sequenced after Quackback cutover
**Goal:** the cloudroof funnel only builds a gated issue after a cofounder "Accepted for Build" in Quackback; auto-build after N proven builds.
**Requirements:** KTD4, build-gate decision. **Dependencies:** U5 + the Quackback cutover ([[project_quackback_decision_layer]] — NOT yet live).
**Files:** `pipeline/wgmesh_pipeline/poller.py` (claim gate), `pipeline/wgmesh_pipeline/config.py` (`SERVICE_BUILD_GATE`, `SERVICE_AUTOBUILD_AFTER_N`), `pipeline/tests/test_service_accept_gate.py`.
**Approach:** Before the cloudroof instance claims a `service` issue for spec, check the Quackback gtm-decision stream for an accept on that issue (reuse the QuackbackForge gtm-stream contract — label-keyed `surface:service`+accepted). Gate active until N merged builds, then `SERVICE_BUILD_GATE=off` (auto). Until Quackback is live, this unit is a no-op stub (gate config defaults to manual/off) and the funnel is run via controlled trigger.
**Test scenarios:** gated + not-accepted → issue not claimed; gated + accepted → claimed; after N builds → gate flips to auto; gate off → claims like wgmesh. Edge: Quackback unreachable → fail-closed (don't build). `Covers F: accept-gate first N.`

---

## Scope boundaries

- **In:** cloudroof-eu CI (impl-judge + build) + wrangler CD; surface-gate inversion; 2nd
  systemd instance + provision parameterization; live provision + smoke; the Quackback gate (U6).
- **Deferred to follow-up:** extending pulse/supervisor metrics to the cloudroof instance;
  flipping the gate to auto after N (U6's second half, tune later); service-side ideation
  (goal-sprint emitting service issues — already partly works via observation routing); LLM
  surface auto-classifier for unlabeled manual issues.
- **Outside this funnel's identity:** executing non-code GTM (humans); the wgmesh product
  pipeline (untouched); the Quackback forge cutover itself (independent track, U6 depends on it).

## Sequencing

U1, U2, U3 are independent and parallelizable. U4 depends on U3. U5 depends on U1–U4 (the MVP
proof). U6 depends on U5 + the Quackback cutover — ships last / when Quackback lands. **MVP
(slice-1, full chain incl deploy) = U1–U5**; the Quackback gate is U6.

## Risks & dependencies

- **Box capacity:** 2 pipeline processes on one cpx22 (~2× LLM/CI/git load). U5 verifies; size
  up if thin. Mitigation: independent DB/env/checkout already isolates them.
- **cloudroof-eu secrets:** needs `CLOUDFLARE_API_TOKEN`, `OPENROUTER_API_KEY`, a cloudroof-scoped
  `WGMESH_BOT_PAT`. Operator-provisioned (U5).
- **Quackback dependency (U6):** the accept-gate blocks on a separate incomplete track. Mitigated
  by shipping U1–U5 first and running the funnel controlled until the gate lands.
- **Deploy blast radius:** auto-deploy to the live customer site. Mitigation: green-main-gated CD
  + the impl-judge gate + (initially) controlled/gated builds.

## Open questions (deferred to execution)

- The "N" in gated-first-N (operator tuning; default e.g. 5).
- Whether cloudroof-eu's existing `spec-merged-build.yml` already covers the build gate or U1
  adds a distinct `ci.yml`.
- Exact `cpx22` headroom → size-up decision (U5, runtime).
