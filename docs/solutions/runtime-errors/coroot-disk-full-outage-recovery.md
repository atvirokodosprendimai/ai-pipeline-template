---
title: "Coroot VPS disk full — 42-hour outage recovery via GitHub Actions"
category: runtime-errors
date: 2026-03-17
tags: [docker, disk-full, hetzner, coroot, github-actions, ci-cd, backup, recovery]
component: coroot-cicd
severity: critical
duration: "42 hours"
repo: atvirokodosprendimai/coroot-cicd
---

## Problem

`table.beerpub.dev` returned HTTP 502 for 42 hours (2026-03-16 04:11 UTC to 2026-03-17 22:49 UTC). The uptime monitor created [issue #60](https://github.com/atvirokodosprendimai/coroot-cicd/issues/60) with 32 automated "still down" comments.

## Root Cause

The weekly `coroot-update.yml` auto-update pipeline ran on 2026-03-16 at 05:51 UTC. During the **Backup Volumes** step, the `backup-volumes.sh` script:

1. **Stopped all data services** (coroot, prometheus, clickhouse, node-agent, cluster-agent) for consistent backup
2. Backed up coroot data (3.1GB) and prometheus (417MB) successfully
3. Started backing up **ClickHouse data (31.9GB)** via `tar czf` inside an alpine container
4. The 75GB disk was already at 80% (58GB used). Writing the compressed ClickHouse archive filled the remaining space
5. **SSH connection broke** (`client_loop: send disconnect: Broken pipe`, exit code 255)
6. The pipeline crashed at the backup step — **never reached deploy or restart steps**
7. Services remained stopped. `restart: always` in docker-compose couldn't restart containers because Docker needs disk space for container metadata
8. Caddy stayed up (wasn't stopped for backup), returning 502 because all upstream services were down

**Disk breakdown at time of outage:**

| Component | Size |
|-----------|------|
| ClickHouse data volume | 31.9GB |
| Coroot data volume | 6.6GB |
| Backups (`/opt/coroot/backups/`) | ~30GB |
| Prometheus data volume | 2.4GB |
| Docker images | 2.25GB |
| **Total** | **~73GB on 75GB disk** |

## Why Recovery Was Difficult

1. **No local SSH key** — the VPS key only existed as a GitHub Actions secret (`VPS_SSH_KEY`), so all recovery had to go through workflows
2. **GitHub Actions dispatch caching** — creating or modifying workflow files triggers re-indexing, during which `workflow_dispatch` returns HTTP 422 for 5+ minutes. New workflows took 2+ hours to become dispatchable
3. **Broken `skip_backup` input** — declared as `type: boolean` but compared with `== 'true'` (string), so boolean `true` never matched
4. **Each pipeline run made things worse** — `docker compose pull` needs disk for image layers, rollback restores volumes, consuming any space that cleanup had freed

## Solution

Modified the **Post-Pipeline Cleanup** job in `coroot-update.yml` (runs `if: always()`) to delete backups, prune Docker, and restart the stack:

```yaml
- name: Cleanup VPS
  run: |
    ssh ... root@$VPS_HOST 'bash -s' <<'CLEANUP'
    set +e
    rm -rf /opt/coroot/backups/*
    docker system prune -f 2>/dev/null || true
    apt-get clean 2>/dev/null || true
    journalctl --vacuum-size=50M 2>/dev/null || true
    cd /opt/coroot && docker compose up -d
    CLEANUP
```

Triggered via: `gh workflow run coroot-update.yml -f force_deploy=true -f skip_backup=true -f skip_staging=true`

Deploy and rollback both failed (disk full), but the `if: always()` Cleanup job:
- Freed 32GB (backups deleted, Docker pruned)
- Disk went from **100% to 60%** (29GB free)
- All containers came up healthy
- External HTTP check returned **200**

### Additional fixes

- **`backup-volumes.sh` disk pre-check** — skips backup when <15GB free, exits 0 so pipeline continues
- **Boolean input fix** — `inputs.skip_backup == true || inputs.skip_backup == 'true'`

## Prevention

1. **Remove backup step** if backups aren't needed (confirmed unnecessary for this instance)
2. **Add ClickHouse TTL/retention** — 32GB volume grows unbounded without data retention policies
3. **Disk space monitoring** — alert at 80% before it becomes critical
4. **Consider disk resize** — Hetzner CAX21 (80GB) to CAX31 (160GB) for ~$7/mo more
5. **Never stop services without a restart guarantee** — use `trap` or a separate `if: always()` step
6. **Pre-deploy recovery workflows** — creating workflows during an incident is unreliable due to GitHub indexing delays

## Key Learnings

- **`if: always()` jobs are your escape hatch** — the only reliable way to execute recovery commands when prior jobs fail
- **GitHub Actions workflow dispatch indexing is unreliable for incident response** — have recovery workflows pre-deployed and tested
- **Backup scripts that stop services must guarantee restart on failure** — the script crashed mid-backup, leaving services stopped with no recovery path
- **75GB is not enough for 32GB ClickHouse + 30GB backups** — capacity planning must account for backup size equal to sum of all volumes
