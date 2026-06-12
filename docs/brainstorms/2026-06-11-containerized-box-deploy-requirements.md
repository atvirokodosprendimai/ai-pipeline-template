# Containerized Box Deploy — Requirements

**Date:** 2026-06-11
**Status:** Ready for planning
**Scope:** Deep — feature (infra/architectural change to how the wgmesh-pipeline box is updated)

## Problem

Updating the LangGraph pipeline box conflates two lifecycles. `provision-pipeline-box.yml`
recreates the Hetzner VM (delete + create + cloud-init, ~13 min) to change anything beyond
code — env, secrets, `MODEL_REGISTRY`, mode. `update-pipeline-box.yml` ships code in-place
(~75 s) but installs the toolchain live (goose, Go, ggshield), which has broken in practice
(the ~70 s Go-install race that cost two gate decisions; the ggshield/urllib3 conflict).

The deployed artifact is not provably the artifact CI tested: deploy is `git reset --hard` +
`pip install -e` live, which can resolve or behave differently than CI. There is no atomic
rollback — reverting a bad deploy means another git-pull, and a half-run provision (a cancel
landed after server-delete tonight) leaves a destroyed box.

## Primary goal

**Atomicity and rollback.** A deploy installs an artifact that CI already built and tested,
swaps to it atomically, and can be reverted to the exact prior artifact in one action. Server
recreation is never the path for an app or config update.

Secondary pains this same mechanism removes: toolchain install races (baked at build), and
server-lifecycle coupling (the VM is never recreated to ship the app).

## Approach (selected)

Docker image, built and tested in CI, deployed by pulling a commit-SHA tag and swapping the
container. Chosen over a VM-side versioned-release-dir scheme because only the image bakes the
toolchain (killing the install races) and decouples server lifecycle, collapsing the primary
ask and two secondary pains into one mechanism.

## Requirements

- **R1 — Baked toolchain image.** `pipeline/deploy/Dockerfile` builds an image containing the
  pipeline plus its full runtime toolchain: python, goose, Go 1.25.5, ggshield — all version-
  pinned. No tool is installed at deploy time.
- **R2 — CI build-test-push.** On merge to main, CI builds the image, runs the pipeline test
  suite **inside the image**, and pushes it to `ghcr.io` tagged by commit SHA (and a moving
  `latest`). A failed in-image test fails the build and blocks the push.
- **R3 — Atomic deploy.** A deploy action pulls a specified SHA tag on the box and swaps the
  running container to it, then health-checks the service. No server recreation. Target under
  ~2 minutes.
- **R4 — One-action rollback.** Re-deploying a prior SHA tag restores that exact prior
  artifact. The previous good tag is recoverable without a rebuild.
- **R5 — Persistent local state.** The wgmesh working tree and the Go module cache live on a
  persistent host volume mounted into the container, surviving container swaps so deploys do
  not re-clone or re-download. (Per session 2026-06-10, the model-litter dirs `go/`, `go-cache/`,
  `pipeline-output/` are managed by the implement node, not the image — the volume holds the
  legitimate checkout + module cache only.)
- **R6 — Secrets stay on the host.** Runtime secrets are injected from the host env file
  (`/etc/wgmesh-pipeline/env`) via `--env-file`, never baked into the image and never in
  registry layers. A config/secret change is a host-file edit + container restart — not a
  provision.
- **R7 — Provision shrinks, doesn't vanish.** `provision-pipeline-box.yml` remains for
  first-time infra standup only: create the VM, install docker, create the volume, write the
  env file, pull and start the first container. It is no longer the path for app or config
  updates.
- **R8 — Keep the git-pull fast path as a dev escape hatch.** `update-pipeline-box.yml` (the
  ~75 s in-place git-pull deploy) is retained for ad-hoc development iteration, not retired.
  The image deploy is the production path; the git-pull path is the break-glass alternative.

## Success criteria

- A merge to main yields a SHA-tagged image whose push is gated on the suite passing inside it.
- A deploy is pull + container swap with no server recreate, env and persistent state intact.
- Rollback to the immediately prior SHA is a single dispatch and restores the exact artifact.
- A Go or ggshield install cannot occur at deploy time — the toolchain is present by image build.

## Scope boundaries

**Deferred for later**
- Per-goose-run sandbox containers (running each goose invocation in its own throwaway
  container — already noted as a follow-up in the current Dockerfile).
- Zero-downtime / blue-green deploy. Single box; a brief restart between container swaps is
  acceptable.

**Outside this change**
- Turso state store and Langfuse remain as-is (already remote/decoupled).
- Multi-box or horizontal scaling.

## Dependencies / assumptions

- Registry is `ghcr.io` (the org is already on GitHub). The image is assumed **private** →
  the box needs a pull credential (deploy token or read-scoped PAT); CI pushes with its
  workflow token. *Decision deferred to planning.*
- The box gains a docker runtime (added in the shrunk provision, R7).
- Assumption: goose session data does not need to persist across container swaps (sessions are
  not reused across issues). If planning finds a reuse case, add it to the R5 volume.

## Outstanding questions (for planning)

1. **Build trigger granularity** — rebuild on every main merge, or only when `pipeline/`
   (or the Dockerfile) changes, to skip docs-only/state-commit merges.
2. **Registry auth on the box** — deploy token vs read PAT vs making the image public; how the
   pull credential is written and rotated.
3. **Deploy/rollback surface** — a new `deploy-pipeline-box.yml` workflow_dispatch taking a SHA
   (default `latest`), or extend `update-pipeline-box.yml`. Rollback = same workflow with a
   prior SHA.
4. **Image size / build cache** — the Go toolchain layer (~600 MB) wants aggressive layer
   caching so per-merge builds stay in the low-minutes range.
5. **First-container ordering in provision** — volume init + env write must precede the first
   `docker run`; define the provision step order.
