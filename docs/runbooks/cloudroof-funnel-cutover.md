# Runbook — Cloudroof service funnel cutover (U5)

Created: 2026-06-22
Owner: operator (mints secrets/PAT, runs provision, flips live)
Plan: `docs/plans/2026-06-22-002-feat-cloudroof-service-funnel-plan.md`

Stands up the **second** co-resident pipeline instance (`cloudroof-pipeline`) on
the existing box, targeting `cloudroof-eu`, so `surface:service` issues get
built → PR'd → judge-gated merged → `wrangler deploy`'d to cloudroof.eu. Mirrors
the merge-lane-heal cutover discipline: **shadow-prove first, then flip live**.

## What's already on main (the code units — inert until provisioned)
- **U3 surface-gate inversion** — `Config.surface_home` (`SURFACE_HOME` env).
  Default `product` (wgmesh unchanged); the cloudroof env sets `service` →
  builds service issues, blocks product/unknown.
- **U4 2nd instance** — `pipeline/deploy/cloudroof-pipeline.service` (shares the
  wgmesh code install + venv, distinct env/checkout/DB), `set-box-env.yml` +
  `update-pipeline-box.yml` parameterized by `service` input (default wgmesh =
  unchanged), and the non-destructive **`Install Cloudroof Instance`** workflow.
- **U1/U2 in cloudroof-eu** — `impl-judge.yml` + `ci.yml` (CI gates) and
  `deploy.yml` (`wrangler deploy` CD). Wired but require secrets (below).

> Nothing changes runtime behavior until the workflows run + the env flips live.
> The wgmesh instance is byte-unchanged: it never sees `SURFACE_HOME` and the box
> workflows default `service=wgmesh`.

## Pre-flight: secrets & PAT (operator)

| Secret / var | Where | Purpose |
|---|---|---|
| `CLOUDROOF_BOT_PAT` | ai-pipeline-template repo (Actions) | Fine-grained PAT scoped to **cloudroof-eu**, read+write (contents, PRs, issues). The 2nd instance's bot token (written to the cloudroof env as `WGMESH_BOT_PAT`). |
| `OPENROUTER_API_KEY` | **cloudroof-eu** repo | impl-judge gate (DeepSeek via OpenRouter). Same key shape as wgmesh. |
| `CLOUDFLARE_API_TOKEN` | **cloudroof-eu** repo | `wrangler deploy` CD. Scope: Workers Scripts:Edit + the creu account. |
| `CLOUDFLARE_ACCOUNT_ID` | **cloudroof-eu** repo | Account the `creu` Worker lives in. |
| `PUSH_TOKEN` | cloudroof-eu (already set) | existing spec-merged-build assigner. |

Mint the PAT at github.com → Settings → Developer settings → Fine-grained tokens,
resource owner `atvirokodosprendimai`, repo `cloudroof-eu` only.

## Step 1 — cloudroof-eu CI/CD required checks (U1/U2)

After `OPENROUTER_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` are set:

1. Confirm `impl-judge.yml`, `ci.yml`, `deploy.yml` are on cloudroof-eu `main`.
2. Make **`impl-judge`** and **`ci`** required status checks on the cloudroof-eu
   `protect-main` ruleset, with auto-merge enabled (mirror wgmesh's ruleset).
   - This is the gate that lets the box's judge-gated auto-merge actually merge.
3. Trigger a no-op PR (or wait for the first bot PR) and confirm both checks post.
4. `deploy.yml` fires only on push to `main` (green) — verify a manual merge to
   main deploys `./dist` and the site serves it.

## Step 2 — box capacity check

The box runs 2 pipeline processes now (~2× LLM/CI/git load). On the box:

```
systemctl status wgmesh-pipeline | head
free -m ; nproc ; df -h /opt
```

`cpx22` (2 vCPU / 4 GB) headroom is thin under concurrent goose+go builds. If
memory/CPU is saturated during the smoke (Step 4), size up the VM (cpx32) via a
fresh `Provision Pipeline Box` for wgmesh, then re-run `Install Cloudroof Instance`.
Record the decision here.

## Step 3 — install the 2nd instance (shadow)

Run **Actions → Install Cloudroof Instance** with:
- `server_name=wgmesh-pipeline` (same box)
- `pipeline_mode=shadow`

This is **non-destructive** — it never recreates the server (that would kill the
wgmesh instance). It writes `/etc/cloudroof-pipeline/env`, clones
`/opt/cloudroof-checkout`, installs + enables `cloudroof-pipeline.service`.

Verify on the box:
```
systemctl is-active cloudroof-pipeline
journalctl -u cloudroof-pipeline -n 40 --no-pager   # expect "tick" lines, shadow
```
In shadow the instance polls + plans but performs no forge writes. Confirm it
**gates correctly**: a `surface:service` cloudroof-eu issue advances; a
`surface:product` one is blocked (`block_product` in the journal).

## Step 4 — live smoke (one real issue, end-to-end)

1. Pick one existing cloudroof-eu service issue (e.g. the rerouted onboarding
   widget). Confirm it carries `surface:service`.
2. Flip the cloudroof instance live (keep wgmesh untouched):
   ```
   Actions → Set Pipeline Box Env
     service = cloudroof
     env_set = PIPELINE_MODE=live,CONTROL_LOOP_MODE=live
   ```
   (restarts only `cloudroof-pipeline`.)
3. Watch: spec PR → impl PR (`fix: Issue #N`) → `impl-judge`+`ci` green →
   judge-gated auto-merge → `deploy.yml` → cloudroof.eu serves the new asset.
4. No hand edits at any step = MVP proven (Outcome / AE).

## Rollback

- Stop the 2nd instance: `systemctl disable --now cloudroof-pipeline`. The wgmesh
  instance is entirely independent (own env/DB/checkout/unit) and unaffected.
- Back to shadow without uninstalling: `Set Pipeline Box Env service=cloudroof
  env_set=PIPELINE_MODE=shadow,CONTROL_LOOP_MODE=shadow`.
- Deploy blast radius: `deploy.yml` is green-main-gated + behind the impl-judge
  gate; revert a bad merge on cloudroof-eu and the next push redeploys the prior
  `./dist`.

## Deferred (not this cutover)

- **U6 Quackback accept-gate** — gated-first-N build approval. Ships after the
  Quackback forge cutover (`docs/runbooks/quackback-cutover.md`). Until then the
  funnel runs controlled (limited issues), NOT open auto-build.
- Pulse/supervisor metrics extended to the cloudroof instance.
- Auto-flip the build gate to open after N proven builds.
