# Container Cutover Runbook

Use this runbook to cut the pipeline box over to the GHCR-backed container
deployment path. Do not run live box, SSH, Hetzner, or Docker commands until an
operator is ready to perform the cutover.

1. Set the `GHCR_PULL_TOKEN` secret in this repository.

   Use the GitHub UI, or:

   ```bash
   gh secret set GHCR_PULL_TOKEN
   ```

2. Confirm `build-pipeline-image.yml` ran green on `main` and the image exists:

   ```text
   ghcr.io/<owner>/wgmesh-pipeline:latest
   ```

3. Run `provision-pipeline-box.yml` with `reset_queue=false`.

   This is the shrunk provision path: Docker install, persistent volume dirs,
   `/etc/wgmesh-pipeline/env` update, GHCR login, and systemd container startup.
   Do not use the legacy full-box app/toolchain install path.

4. Verify the box is ticking.

   SSH in and watch the service journal:

   ```bash
   journalctl -u wgmesh-pipeline -f
   ```

   Confirm fresh `tick` log lines appear.

5. Gate decision.

   If the service is ticking, proceed to step 6. If not, investigate
   `journalctl -u wgmesh-pipeline` before continuing.

6. Test deploy and rollback.

   Trigger `deploy-pipeline-box.yml` with `sha=latest` and confirm the health
   check passes. Then trigger it with a bad SHA such as `notareal-sha` and verify
   the workflow fails before swapping the running service, or auto-rolls back if
   a swapped container fails health.

Durable Turso state survives container recreates because it is external to the
container.

## Two image lanes (by design)

- `build-pipeline-image.yml` — every `pipeline/**` push to main builds
  `ghcr.io/<owner>/wgmesh-pipeline:<sha>` + `:latest`. This is the box
  self-deploy cadence (#1599 U14: the box merges its own code and deploys
  the exact merged SHA).
- `release.yml` — operator-cut `v*` tags build versioned images from the
  TESTED bytes (see #1673). Human-meaningful milestones, not every merge.
