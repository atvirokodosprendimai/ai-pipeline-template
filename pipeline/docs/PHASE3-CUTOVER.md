# Phase 3 — Full-Live Cutover Runbook

This is the operational procedure to take the self-hosted LangGraph pipeline
from spec-only to **full live** (box owns the loop through merge). The code is
ready and tested (shadow + spec-only + live paths, 79 tests). Nothing here is
applied automatically — cutover is a deliberate operator action.

> The box never merges high-risk diffs blind and never merges unreviewed. The
> gate auto-merges only low-risk changes with green tests + clean sanitise + no
> blocking review finding; everything else escalates to `needs-human`. This is
> verified end-to-end (`pipeline/tests/test_live_e2e.py`).

## Preconditions

1. **Run environment** with:
   - `WGMESH_BOT_PAT` — fine-grained PAT (or app token) with `issues:write`,
     `contents:write`, `pull_requests:write` on `atvirokodosprendimai/wgmesh`.
     (This replaces the expired `PUSH_TOKEN`. Rotate on a cadence.)
   - `ZAI_API_KEY` + `ANTHROPIC_HOST=https://api.z.ai/api/anthropic` — Goose LLM.
   - `LANGSMITH_API_KEY` — online scoring (optional; degrades to no-op if unset).
   - `TARGET_REPO=atvirokodosprendimai/wgmesh`.
   - Goose CLI + Python 3.11 + the `pipeline` package installed.
2. A **host** (Hetzner VM or co-located box) — see Phase 4 for the systemd unit.

## Staged rollout

Do not jump straight to live. Walk the modes:

1. **Shadow** (`PIPELINE_MODE=shadow`): run against real wgmesh issues. No
   GitHub writes (verified). Confirm the loop classifies/specs/implements and
   the gate decisions look right in the logs / LangSmith.
2. **Spec-only** (`PIPELINE_MODE=spec-only`): box opens real spec PRs and stops;
   Actions still build/merge. Run the spec-parity harness
   (`pipeline/evals/spec_parity.py`) against a few issues to confirm box specs
   match the Actions-chain specs before trusting them.
3. **Live** (`PIPELINE_MODE=live`): box owns through merge. Proceed only after 1–2
   look healthy.

## Disabling the Actions chain (at live cutover only)

When `PIPELINE_MODE=live` is running, retire the three wgmesh workflows so the
box and Actions don't both act. **Keep the files** (fallback) — only gate them
off. In `atvirokodosprendimai/wgmesh`, add `if: false` to the top job of each:

- `.github/workflows/goose-triage.yml`
- `.github/workflows/goose-build.yml`
- `.github/workflows/spec-auto-approve.yml`

```yaml
jobs:
  <top-job>:
    if: false   # PHASE 3 CUTOVER: box owns the loop; re-enable to roll back
    runs-on: ubuntu-latest
```

This is a separate PR in the wgmesh repo. Do it as the last step of going live,
after the box has run live cleanly on at least one issue.

## Verification checklist (first live run)

- [ ] A low-risk issue (e.g. docs/config) → box opens an impl PR **and merges it**;
      issue closed; LangSmith shows a run scored `merged`.
- [ ] A high-risk issue (touches auth/crypto/wireguard-key/secret/payment, or a
      large diff) → box opens the PR but **escalates** with `needs-human`, no
      merge; LangSmith run scored `escalated`.
- [ ] No duplicate action from the (now-disabled) Actions workflows.
- [ ] `sanitise.sh` ran on every spec/PR body before any write (fail-closed).

## Rollback

Fast and clean — the box holds no un-migrated state (sqlite is the box's working
queue; **GitHub is the source of truth** for issues/PRs):

1. Stop the box (`systemctl stop wgmesh-pipeline`) or set `PIPELINE_MODE=shadow`.
2. Remove `if: false` from the three wgmesh workflows → Actions chain resumes.
3. No data migration needed; the box re-reconciles from GitHub labels on next start.
