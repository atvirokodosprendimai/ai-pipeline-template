---
title: "Workflow disposition map — .github/workflows/ under the Forge-portable SDLC"
status: active
date: 2026-06-11
parent: docs/plans/2026-06-11-003-refactor-forge-portable-sdlc-plan.md (U6)
sequencing: docs/plans/2026-06-09-002-refactor-retire-actions-langgraph-cutover-plan.md (#1599)
type: refactor
---

# Workflow disposition map

This is a **disposition map, not a deletion PR**. No workflow is removed by this document;
actual migration executes under #1599's phases (A convergence → B control loop → C
monitoring/pulse → D CI → E resilience), with disable-then-delete per phase (#1599 U13 is the
final trim). Each MOVE-TO-BOX row cites the matching #1599 unit; rows with no matching unit
say "not yet sequenced in #1599".

The **gh-CLI-bearing workflows (13 per the coupling inventory)** — observation-loop,
pipeline-health, strategy-audit, bot-pr-review-merge, heartbeat-pr-automerge, pr-disposition,
health-check, pipeline-error-rate, checkout-monitor, supervisor-rank, goal-sprint,
compound-capture, compound-synthesize — **must not gain new `gh` usage** while they await
migration; the grep-gate enforcing this lands in U8 of the parent plan. They are exempt from
the gate only until removed.

`ci.yml` and `release.yml` are **new in this branch** (parent plan's thin-CI units): `ci.yml`
absorbs the test/lint/sanitise/PII/spec-validation checks on PR+push; `release.yml` absorbs
tag → image publishing. The KEEP-THIN rows below name which of the two absorbs each legacy
CI workflow.

## Disposition table (39 legacy workflows)

Legend: **KEEP-THIN** = stays normal git-flow CI on the host forge, absorbed/replaced by
`ci.yml`/`release.yml`. **MOVE-TO-BOX** = the LangGraph box owns the job; gh CLI calls become
Forge protocol methods; the workflow is disabled after parity, deleted at #1599 U13.
**RETIRE-TO-SCRIPT** = becomes a box-local script under `pipeline/deploy/` or an operator
runbook. **RETIRE** = dropped outright.

| Workflow file | Purpose (one line) | Disposition | Target / notes |
|---|---|---|---|
| `pipeline-ci.yml` | Pytest + lint for `pipeline/` on PR/push | KEEP-THIN | Absorbed by `ci.yml` (test job). Bot-PR runs move to the box at #1599 U9; `ci.yml` remains for external/host PRs (#1599 U10). |
| `sanitise-wall.yml` | Sanitise-gate wall on push/PR (public-repo leak guard) | KEEP-THIN | Absorbed by `ci.yml` (sanitise job). Box-side equivalent at #1599 U9; external-PR guard must never lapse (#1599 U10). |
| `pii-policy-check.yml` | PII/secret policy check on PRs | KEEP-THIN | Absorbed by `ci.yml` (pii-policy-check job; head/base SHA contexts are GitHub-specific by design — rewritten per host with the thin CI file). Legacy workflow stays active for one bake cycle, disabled with the U2 wave. Same U9/U10 split as sanitise-wall — fork PRs are highest-PII-risk, the Actions copy is the retained sandbox. |
| `spec-validation.yml` | Validates `specs/issue-N-spec.md` shape on spec PRs | KEEP-THIN | Absorbed by `ci.yml` (structural check via validate-spec.sh). Labeling/auto-approve remains orchestration in the legacy workflow until the box owns it (U2/U15). Note: #1599 U2 also lists it in the deterministic dev-chain disable set — the check survives as a `ci.yml` job even after the orchestration trigger is box-owned. |
| `build-pipeline-image.yml` | Builds + pushes the pipeline container image on push | KEEP-THIN | Absorbed by `release.yml` (tag → image). Push-triggered build retires once tag-driven release is proven. |
| `observation-loop.yml` | 3×/day funnel-stage observation: read issues/PRs, LLM assessment, emit actions | MOVE-TO-BOX | Box-scheduled observation graph node; LLM assessment step stays, `gh issue/pr list` reads become `forge.list_issues`/`forge.list_prs`. #1599 U3. |
| `pipeline-health.yml` | Self-healing sweep every 30 min: detect stuck items, heal, commit state | MOVE-TO-BOX | Box self-heal job; healing actions via forge methods, state to Turso (kills the state-PR lane); mutation-assert lesson stays. #1599 U4. |
| `pipeline-error-rate.yml` | Computes workflow error rate every 15 min | MOVE-TO-BOX | Box monitor deriving error rate from its own run state (Turso) instead of `gh run list`. #1599 U7. |
| `supervisor-rank.yml` | Ranks pipeline clogs every 4 h, publishes recommendation | MOVE-TO-BOX | Box rank module (dwell × downstream-blocked), read-only recommend; idempotent fingerprint gate. #1599 U5. |
| `strategy-audit.yml` | Daily strategy-drift audit, opens doc PR on material drift | MOVE-TO-BOX | Box audit job; LLM drift assessment stays, material-drift fingerprint gate stays, doc PR via `forge.create_pr`. #1599 U6. |
| `pr-disposition.yml` | 6-hourly PR queue self-processing: classify → merge/stale-close/escalate | MOVE-TO-BOX | Box disposition node; classification logic ports as-is, merges/closes via `forge.merge_pr`/`forge.close_pr`. #1599 U2. |
| `goal-sprint.yml` | Weekly CE ideate→plan→intent emission feeding the spec chain | MOVE-TO-BOX | Weekly box tick; LLM ideate/plan stays, intent issue via `forge.create_issue`, sanitise gate stays in path. #1599 Phase B (design table); no dedicated unit — not yet sequenced in #1599. |
| `bot-pr-review-merge.yml` | 5-min lane: review + merge label-gated bot PRs | MOVE-TO-BOX | Box review+merge lane; `approved-for-build`/`needs-human` label gates become box state checks (de-labeling per parent plan), merge via `forge.merge_pr`. #1599 U2. |
| `heartbeat-pr-automerge.yml` | Fast-lane auto-merge for scoped state-JSON PRs | MOVE-TO-BOX | Dissolves: box writes state to Turso directly, so the state-PR lane disappears; residual file-scope guard moves into the box's `forge.merge_pr` gate. #1599 U2. |
| `health-check.yml` | 15-min liveness probe of pipeline surfaces | MOVE-TO-BOX | Box self-monitoring + the off-box dead-man's-switch watches the box itself. #1599 U7 (self-monitoring) + U11 (off-box watcher). |
| `copilot-triage.yml` | On new issue: LLM triage → spec assignment (judgment tier) | MOVE-TO-BOX | Box triage node; LLM judgment step stays (behavioral, not exact-match, parity), issue ops via forge methods. #1599 U15. |
| `copilot-undraft.yml` | Auto-marks bot draft PRs ready for review | MOVE-TO-BOX | Deterministic box step: `forge.mark_ready` on its own spec/impl PRs. #1599 U2. |
| `impl-merged-close.yml` | Closes the source issue when its impl PR merges | MOVE-TO-BOX | Box lifecycle step on merge event: `forge.close_issue` + comment; kills the false-stuck stale-sweep class. #1599 U2. |
| `spec-merged-build.yml` | On spec PR merge: trigger the build stage | MOVE-TO-BOX | Internal box state transition (spec→build) — no cross-workflow dispatch needed once one process owns the chain. #1599 U2. |
| `approve-build.yml` | On spec PR review event: gate the build approval | MOVE-TO-BOX | Box reads review state via `forge.get_reviews` and transitions; label side-effects become best-effort mirrors. #1599 U2. |
| `compound-capture.yml` | On PR: capture solved-problem learnings into docs | MOVE-TO-BOX | Box post-merge hook appending learnings; `gh pr view` becomes `forge.get_pr`; sanitise gate stays. Not yet sequenced in #1599. |
| `compound-synthesize.yml` | Weekly synthesis of captured learnings into docs PR | MOVE-TO-BOX | Weekly box job; LLM synthesis stays, doc PR via `forge.create_pr`. Not yet sequenced in #1599. |
| `checkout-monitor.yml` | 6-hourly synthetic Polar checkout probe | MOVE-TO-BOX | Box Polar synthetic module — share one implementation with the #1589 funnel-instrumentation synthetic. #1599 U16. |
| `polar-discovery.yml` | One-shot Polar product discovery | MOVE-TO-BOX | One-shot box task in the same Polar module as the synthetic. #1599 U16. |
| `mentisdb-smoketest.yml` | Daily MentisDB connectivity smoketest | MOVE-TO-BOX | Box telemetry self-check, non-fatal/best-effort (telemetry-writes lesson). #1599 U8. |
| `rah-application-decide.yml` | Manual dispatch: accept/reject a RAH bounty application | MOVE-TO-BOX | Box RAH client module calling the RAH API directly (dispatch wrapper unneeded). Not yet sequenced in #1599 — #1599 explicitly keeps `rah-*` out of scope, so this is post-cutover. |
| `rah-applications-all.yml` | Manual dispatch: read-only list of RAH applications | MOVE-TO-BOX | Same RAH client module, read-only call. Not yet sequenced in #1599 (rah-* out of #1599 scope). |
| `rah-bounty-dispatch.yml` | Manual dispatch: post a RAH bounty | MOVE-TO-BOX | Box escalation ladder step (me → Codex → RAH) posting via RAH API. Not yet sequenced in #1599 (rah-* out of #1599 scope). |
| `rah-bounty-review.yml` | Manual dispatch: read-only review of a RAH bounty | MOVE-TO-BOX | Same RAH client module. Not yet sequenced in #1599 (rah-* out of #1599 scope). |
| `rah-profile-probe.yml` | Manual dispatch: probe RAH profile/API health | MOVE-TO-BOX | RAH client self-check. Not yet sequenced in #1599 (rah-* out of #1599 scope). |
| `sync-labels.yml` | Syncs the repo label set from `labels.yml` | RETIRE | Labels become best-effort mirrors after the parent plan's lifecycle de-labeling — no gate depends on them, so drift is cosmetic. #1599 carries it as Phase C open question; this map resolves it to RETIRE. |
| `deploy-pipeline-box.yml` | Manual dispatch: deploy the pipeline container to the box | RETIRE-TO-SCRIPT | `pipeline/deploy/run-container.sh` (exists) + guarded self-deploy on the box (#1599 U14). |
| `update-pipeline-box.yml` | Manual dispatch: update code/service on the box | RETIRE-TO-SCRIPT | `pipeline/deploy/` update script; superseded by U14 self-deploy + U12 rebuild. |
| `provision-pipeline-box.yml` | Manual dispatch: provision a Hetzner box from zero | RETIRE-TO-SCRIPT | `pipeline/deploy/` rebuild script, invocable by the off-box watcher. #1599 U12. |
| `provision-langfuse.yml` | Manual dispatch: provision the Langfuse stack | RETIRE-TO-SCRIPT | Folded into the `pipeline/deploy/` rebuild script (pin third-party images per lesson). #1599 U12. |
| `terraform-deploy.yml` | Terraform infra apply on push/dispatch | RETIRE-TO-SCRIPT | Operator runbook + `pipeline/deploy/` wrapper; infra changes are rare, operator-run. #1599 U12. |
| `diagnose-pipeline.yml` | Manual dispatch: diagnostic dump of pipeline state | RETIRE-TO-SCRIPT | Box-local diagnostic script + ops runbook (gitops state probe pattern). #1599 U7. |
| `langfuse-probe.yml` | Manual dispatch: Langfuse ingestion probe | RETIRE-TO-SCRIPT | Box-local telemetry self-check script; #1599 U8 sequences the disable — prove box-side scoring before retiring (observability never dark). |
| `langfuse-llm-connection.yml` | Manual dispatch: Langfuse LLM connection check | RETIRE-TO-SCRIPT | Same box-local telemetry self-check; #1599 U8 sequencing applies. |

## Summary counts

| Disposition | Count |
|---|---|
| KEEP-THIN (absorbed by `ci.yml`/`release.yml`) | 5 |
| MOVE-TO-BOX (20 with a #1599 unit or phase; 7 not yet sequenced in #1599: goal-sprint, compound-capture, compound-synthesize, rah-* ×5 — goal-sprint has Phase B grouping but no unit) | 25 |
| RETIRE-TO-SCRIPT (`pipeline/deploy/` or ops runbook) | 8 |
| RETIRE | 1 |
| **Total legacy workflows mapped** | **39** |

Plus the 2 new thin workflows added by this branch (`ci.yml`, `release.yml`) — the keep
surface, not part of the legacy inventory. End state per #1599 U13 + parent plan U10:
`.github/workflows/` holds `ci.yml`, `release.yml`, one hardened external-PR CI workflow,
and (until their post-cutover box port) the `rah-*` files.
