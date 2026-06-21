# Actions = CI/CD only — end-state inventory & migration order

Created: 2026-06-21
Plan: `docs/plans/2026-06-21-006-refactor-actions-cicd-only-plan.md` · Issue: #1599

The north-star invariant for the #1599 cutover: **GitHub Actions holds only the
CI/CD pipeline, and the autobox is just another developer** — its PRs run the
same Actions CI a human's PR does. Everything else leaves Actions for the box or
off-box.

## The one CI already exists: `ci.yml`

`.github/workflows/ci.yml` (from the 2026-06-11 forge-portable SDLC plan) is the
unified CI: it runs on `pull_request` + `push:[main]` for **all authors** (no
bot/fork skip), is **secretless** (no `secrets.*`, no `pull_request_target`),
forge-portable, and runs `pipeline-tests` · `sanitise-wall` · `pii-policy-check`
· `spec-validation` · `gh-free-gate`. It is exactly the "one CI, autobox is just
another developer" target — and it predated the Phase D detour.

**Phase D was redundant and has been reverted** (this change): `external-pr-ci.yml`
(#1934) duplicated ci.yml's leak guards for non-bot PRs, and the box-posted
`ci/guards` status (#1938) gated bot PRs that ci.yml already gates. Both removed;
the box no longer runs or posts its own CI.

## Kept on Actions (per repo)

| Surface | What | Repo |
|---|---|---|
| **CI** | `ci.yml` — build/test + sanitise + PII + spec-validation, all authors, secretless | meta + (to build) seed |
| **CD** | image build on push + box deploy on merge, gated on CI green | meta |

CD stays in Actions (RR5): a developer's CI/CD includes deploy. This **supersedes
#1599 U14** (box guarded self-deploy) — the box does not deploy itself; Actions
CD does, on merge, like for any developer. `build-pipeline-image.yml` (push) +
`deploy-pipeline-box.yml` + the `#1928` auto-deploy-on-merge wiring stay.

## Leaves Actions (→ box / off-box), in order

Strangler throughout — disable an Actions workflow only after its box equivalent
bakes. Each step maps to a #1599 phase.

1. **CI invariant + Phase-D reversal** — *done* (#1948): ci.yml is the CI; external-pr-ci + box ci/guards removed.
2. **Make ci.yml the required gate** — *meta done*: `protect-main` (13925617) now requires `pipeline-tests` / `sanitise-wall` / `pii-policy-check` (ci.yml jobs); the standalone `pipeline-ci` / `sanitise-wall` / `pii-policy-check` workflows are disabled. Reusable: `scripts/ruleset/apply-required-checks.sh`. **wgmesh deferred** — its `protect-main` (12831947) already requires `impl-judge` / `status-check` / `build-and-push`; **add** `build-test` to that set (don't replace), and only after conflict-heal drains its CONFLICTING bot PRs (#755, #744 at time of writing).
3. **Seed repo CI** — *done* (`wgmesh#798`): `ci.yml` runs go build/test/vet for all authors, secretless. `impl-judge` stays its own secret-bearing, same-repo-gated workflow (folding it into the secretless lane would expose its LLM-judge key to forks). wgmesh has no `docs/outreach`/`docs/customers`, so the meta path-scoped PII guard is N/A there; impl-judge's safety axis covers PII/secret on bot PRs.
4. **Loop → box** (#1599 Phase B): goal-sprint, observation, supervisor, strategy, conflict-heal, heartbeat-automerge, requeue, nongoose-shadow.
5. **Monitoring → box** (#1599 Phase C): health, error-rate, diagnose, checkout-monitor, langfuse ×3, mentisdb, control-replay.
6. **Provisioning → box/off-box** (#1599 Phase E): provision box/langfuse/quackback, set-box-env, terraform.
7. **GTM/social → box or elsewhere**: daily-release-notes, release, social drips.
8. **RAH last**: the `rah-*` subsystem (#1599 KTD6 keeps it out of scope until a separate effort).

When done, `.github/workflows/` per repo holds only `ci.yml` + CD (+ `rah-*` until step 8).

## Notes

- **impl-judge = just another CI test** (RR3): it runs as a job in the seed CI where a spec exists; no box-posted status, no bespoke gate. Fail-closed preserved.
- **Single-identity concentration is unchanged.** Moving CI to Actions does not add a control the box cannot forge (CI runs on the autobox's own trusted branch). The off-box / scope-split-PAT hardening from #1599's identity risk stays open.
- **Lesson:** `ci.yml` existed for 10 days; both Phase D and the first draft of plan 006 missed it. Grep `^name: CI` for an existing unified workflow before planning to build "the one CI".
