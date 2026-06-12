# SDLC — host-agnostic runbook

The full development lifecycle without a single `gh` command. The git host
(GitHub today; Gitea/Forgejo or GitLab after a swap per
`pipeline/docs/FORGE-SWAP.md`) provides three commodity services: git
hosting, issue/PR UI, and thin CI (`.github/workflows/ci.yml` +
`release.yml`). Everything else runs on the box.

## The loop

1. **Issue** — created by a human in the host UI, or by the box via the
   Forge protocol (`pipeline/wgmesh_pipeline/forge/protocol.py`). Labels are
   best-effort mirrors for humans; the box's Turso store is authoritative
   state.
2. **Spec** — the box (LangGraph + Goose) authors a spec, pushes
   `bot/spec-N` over ssh (plain git), opens a PR through the forge adapter.
3. **Implement** — same shape on `bot/impl-N`.
4. **Review** — box-side reviewer (a second identity) reviews via the forge
   API. No Copilot, no host-specific review product.
5. **Merge** — distinct-principal gate
   (`pipeline/wgmesh_pipeline/forge/merge_gate.py`): CI green + approval by
   a non-author, merged via forge API. No admin bypass exists on the box.
6. **Resolution tracking** — `forge/gitfacts.py` reads merged resolution
   commits from the clone's `git log`; the host API is only a freshness
   fallback. Identical on every host.
7. **Release** — the box (or operator) cuts `git tag v*` + push; the host's
   `release.yml` builds and publishes the container image. A developer
   action, not an admin one.

## Credentials on the box

| Credential | Identity | Used for |
|---|---|---|
| ssh deploy key | author bot | branch pushes (plain git) |
| forge API token (`WGMESH_BOT_PAT`) | author bot | issues, PRs, labels |
| reviewer token (`WGMESH_REVIEWER_PAT`) | reviewer bot | approvals only |

Two principals, by design: the author can never approve its own PR (the
2026-06-11 `422 Can not approve your own pull request` lesson).

## Walls

- **gh-free gate** (`ci.yml`): CI fails if `gh` CLI usage enters
  `pipeline/wgmesh_pipeline/`. Verified to bite on shell and subprocess
  list forms.
- **Forge conformance** (`pipeline/tests/conformance/`): the behavioral
  contract every adapter passes; the Gitea adapter runs it stubbed in CI
  and live against a dockerized Forgejo on demand (`GITEA_LIVE=1`).

## Per-host notes

See `docs/ci-portability.md` (CI mapping) and `pipeline/docs/FORGE-SWAP.md`
(the actual swap runbook). Porting cost = rewriting the two thin workflow
files + provisioning the two bot accounts; pipeline code is untouched
(`FORGE_KIND` config selects the adapter, fail-closed).
