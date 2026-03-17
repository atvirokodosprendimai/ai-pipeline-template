# Session — Coroot Disk Full 42h Outage Recovery

**Date:** 2026-03-17
**Branch:** `docs/coroot-disk-full-postmortem`

## Context

User shared [GitHub issue #60](https://github.com/atvirokodosprendimai/coroot-cicd/issues/60) — `table.beerpub.dev` had been down for 35+ hours with the uptime monitor posting "still down" comments every ~45 minutes.

## Investigation

- **DNS:** Resolved fine to `91.99.74.36`
- **HTTP:** Caddy returning 502 (reverse proxy alive, upstream dead)
- **Root cause found:** The weekly `coroot-update.yml` auto-update ran on March 16 at 05:51 UTC. The backup script stopped all services, started backing up ClickHouse (31.9GB), and the 75GB disk hit 100%. SSH broke (`broken pipe`, exit 255). Services stayed stopped — no restart path existed.

## Recovery Attempts

### Attempt 1: Create emergency-recovery.yml workflow
- Created via GitHub contents API with `repository_dispatch` and `workflow_dispatch` triggers
- **Blocked:** GitHub Actions takes 2+ hours to index new workflow files for dispatch. Every attempt returned HTTP 422.

### Attempt 2: Modify vps-diagnostics.yml
- Added recovery commands to the existing diagnostics workflow
- **Blocked:** Modifying ANY workflow file (even just step content) triggers GitHub to re-index triggers, breaking dispatch for 5+ minutes

### Attempt 3: Use coroot-update.yml with skip_backup=true
- **Blocked:** `skip_backup` input declared as `type: boolean` but compared with `== 'true'` (string). Boolean `true` from CLI never matched — backup ran anyway

### Attempt 4: Fix backup-volumes.sh with disk pre-check
- Added disk space guard — skip backup when <15GB free, exit 0 to let pipeline continue
- Script ran, detected 0GB free, deleted old backups (freed 29GB), then proceeded to create a NEW backup
- Cancelled after 55 minutes of ClickHouse compression

### Attempt 5: Fix boolean comparison + retry
- Fixed `inputs.skip_backup == 'true'` to `inputs.skip_backup == true || inputs.skip_backup == 'true'`
- Backup correctly skipped, but deploy step failed: `docker compose pull` → `no space left on device` (disk full again from attempt 4's partial backup + rollback consuming freed space)

### Attempt 6 (SUCCESS): Modify Post-Pipeline Cleanup job
- The `Post-Pipeline Cleanup` job runs `if: always()` — executes even after deploy/rollback failures
- Modified its `Cleanup VPS` step to: delete ALL backups → prune Docker → restart stack
- Deploy failed, rollback failed, but **Cleanup ran and recovered everything**

## Result

- Disk: 100% → **60%** (29GB free)
- All containers: **UP** (prometheus healthy, clickhouse healthy, coroot up)
- External check: **HTTP 200**
- Downtime: 42 hours ended at 22:49 UTC

## Artifacts

- `docs/solutions/runtime-errors/coroot-disk-full-outage-recovery.md` — full postmortem documentation
- Multiple commits pushed to `atvirokodosprendimai/coroot-cicd`:
  - Fixed `backup-volumes.sh` with disk space pre-check
  - Fixed boolean input comparisons in `coroot-update.yml`
  - Added recovery logic to Post-Pipeline Cleanup job
  - Added `emergency-recovery.yml` workflow (for future use once indexed)

## Key Learnings

1. **`if: always()` jobs are the escape hatch** for CI/CD recovery
2. **GitHub Actions workflow dispatch indexing is unreliable** for incident response — pre-deploy recovery workflows
3. **Backup scripts that stop services must guarantee restart** even on failure
4. **75GB disk is insufficient** for 32GB ClickHouse + 30GB backups — capacity planning needed
5. **User doesn't need Coroot backups** — should remove backup step entirely
