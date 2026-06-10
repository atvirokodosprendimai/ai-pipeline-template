# Phase 4 — Hetzner Deployment

Stand up the wgmesh-pipeline as a long-running service. All artifacts are in
`pipeline/deploy/`. Production now runs in `PIPELINE_MODE=live` on the Hetzner
`wgmesh-pipeline` box. Two host options remain documented for rebuilds or
rollback — a dedicated Hetzner VM, or co-locate on chimney.

## What ships in this phase

- `deploy/wgmesh-pipeline.service` — systemd unit (graceful SIGTERM drain,
  restart-on-failure, hardening: NoNewPrivileges/ProtectSystem/PrivateTmp).
- `deploy/env.example` — the env contract (secrets live in
  `/etc/wgmesh-pipeline/env`, chmod 600).
- `deploy/deploy.sh` — idempotent install/update: pull → venv → `pip install -e`
  → **run the test suite (never deploy red)** → install unit → restart.
- `deploy/hetzner-provision.sh` — `hcloud` VM provisioning + cloud-init (installs
  Python + Goose CLI).
- `deploy/Dockerfile` — containerized alternative.
- **Security hardening (Attractor borrow):** `build_goose_env` strips every
  secret-shaped env var (PAT, LangSmith key, HCLOUD token, …) before launching
  Goose, re-adding only the LLM credential. The agent never sees the box's
  GitHub token. Verified by `tests/test_goose_env.py`.

## Provision + deploy

**Option A — dedicated Hetzner VM:**
```
HCLOUD_TOKEN=... SSH_KEY=<key> pipeline/deploy/hetzner-provision.sh
# then on the box, as root:
scp pipeline/deploy/env.example root@<ip>:/etc/wgmesh-pipeline/env   # fill, chmod 600
REPO_URL=<this repo> bash deploy.sh
```

**Option B — co-locate on chimney (cheaper, no new VM):**
```
# on chimney, as root: ensure Python 3.11 + Goose CLI present, then
install -d -m 700 /etc/wgmesh-pipeline   # fill env, chmod 600
REPO_URL=<this repo> bash pipeline/deploy/deploy.sh
```

## Secrets to provision (the go-live gate)

| Var | Purpose |
|-----|---------|
| `WGMESH_BOT_PAT` | fine-grained PAT, issues+contents+pull_requests on wgmesh (replaces dead PUSH_TOKEN) |
| `ZAI_API_KEY` + `ANTHROPIC_HOST` | Goose LLM (z.ai/GLM) |
| `LANGSMITH_API_KEY` | online scoring (optional) |

## Bring-up sequence

Current production is **live** (`PIPELINE_MODE=live`). For a fresh rebuild or
rollback rehearsal, start in **shadow** (`PIPELINE_MODE=shadow`, the env
default) — the service runs the full loop against real wgmesh issues with zero
GitHub writes. Watch the logs / LangSmith. Then walk **spec-only → live** per
`PHASE3-CUTOVER.md` (which also covers disabling the three wgmesh Actions
workflows and rollback).

## Observability

- `journalctl -u wgmesh-pipeline -f` for service logs.
- Existing coroot/signoz on the host for system metrics.
- LangSmith for per-run traces + online scores (when `LANGSMITH_API_KEY` set).

## Follow-ups (not in this phase)

- Per-Goose-run sandbox: run each `goose` invocation in its own throwaway
  container (the full Attractor ExecutionEnvironment abstraction) — currently
  Goose runs as a subprocess on the host with a secret-stripped env.
- Secret rotation cadence for `WGMESH_BOT_PAT`.
