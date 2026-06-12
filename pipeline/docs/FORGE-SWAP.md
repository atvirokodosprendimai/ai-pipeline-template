# FORGE-SWAP: moving the SDLC from GitHub to Gitea/Forgejo

The runbook for pointing the box at a Gitea/Forgejo host instead of GitHub.
The pipeline talks to its forge exclusively through the
`wgmesh_pipeline.forge.protocol.Forge` protocol; `GiteaForge`
(`wgmesh_pipeline/forge/gitea.py`) is the second adapter, selected by config.
Nothing in pipeline code references a host directly — the swap is config +
credentials + a thin CI port.

## 1. Adapter selection + endpoint

| Setting | Value |
|---|---|
| `FORGE_KIND` | `gitea` (fail-closed: unknown values raise in `forge/factory.py`) |
| `GITEA_URL` | Forgejo root, e.g. `https://git.example.com` (duck-typed `gitea_url` attr on Config; defaults to `http://localhost:3000` for local conformance) |
| `TARGET_REPO` | unchanged, `owner/repo` form |
| `PIPELINE_MODE` | unchanged — `shadow` / `spec-only` / `live` gates behave identically on every adapter (the write gate is shared machinery) |

Roll out in `shadow` first: every write becomes a `DryRunResult` while reads
exercise the real Gitea API. Promote to `spec-only`, then `live`, exactly as
on GitHub.

## 2. Credentials: two forge accounts (author + reviewer)

GitHub App tokens and `GITHUB_TOKEN` do **not** port. Replace them with two
plain Gitea user accounts — the distinct-principal review gate requires two
identities (self-approval is rejected on both hosts):

1. **Author bot** (e.g. `wgmesh-bot`): API token with
   `write:repository,write:issue` → `WGMESH_BOT_PAT`. Used for all reads and
   author-side writes (issues, labels, PRs, merges).
2. **Reviewer** (e.g. `wgmesh-reviewer`): separate account, repo collaborator
   with write permission, own API token → `WGMESH_REVIEWER_PAT`. Used only by
   `approve_pr` (the adapter sends this token, never the author token —
   asserted by the conformance suite).

Token mint: Forgejo UI → Settings → Applications, or
`forgejo admin user generate-access-token` (see
`tests/conformance/docker-compose.gitea.yml` for exact commands). Scope
minimally; per the allowlist-not-denylist lesson, expose only these two
tokens to the box process.

## 3. Git remote: ssh deploy key swap

The box pushes branches with plain `git push` (no host API), so only the
remote and key change:

```bash
# on the box, in the checkout (WGMESH_CHECKOUT_PATH)
ssh-keygen -t ed25519 -f ~/.ssh/forge_deploy -N "" -C "wgmesh-box"
# add forge_deploy.pub as a DEPLOY KEY with write access on the Gitea repo
# (repo Settings -> Deploy Keys), then:
git remote set-url origin git@git.example.com:owner/repo.git
GIT_SSH_COMMAND="ssh -i ~/.ssh/forge_deploy -o IdentitiesOnly=yes" git fetch origin
```

`push_branch` semantics (force-update of `bot/spec-*` / `bot/impl-*`,
sanitise walls, mode gates) are inherited unchanged from the reference
adapter.

## 4. Thin CI port

Per `docs/ci-portability.md`, exactly two workflow files are the swappable CI
layer. Copy them into the Gitea workflow directory:

```bash
mkdir -p .gitea/workflows
cp .github/workflows/ci.yml .gitea/workflows/ci.yml
cp .github/workflows/release.yml .gitea/workflows/release.yml
```

Both already use only the portable syntax subset (no `type=gha` cache, no app
tokens, no GitHub-only contexts). Two host notes:

- **Runner:** Gitea/Forgejo has no hosted runners. Register an `act_runner`
  and make sure its label matches `runs-on:` (`ubuntu-latest` works if you
  registered it under that label).
- **Registry:** `secrets.GITHUB_TOKEN` exists under the same name in Gitea
  Actions and authenticates to the **Gitea** container registry. If
  `release.yml` should keep pushing elsewhere (ghcr.io), add a custom secret.

The other ~37 `.github/workflows/*.yml` files are GitHub-era orchestration
being retired into the box (#1599 disposition map); they are intentionally
NOT ported.

## 5. Events: the box polls — no webhook work

The box discovers work by polling (`list_needs_triage` / `list_open_issues`
on `POLL_INTERVAL_SECONDS`). It works unchanged against Gitea; no webhook
configuration is required for the SDLC. (Webhook-driven ingestion is an
explicit deferral in the forge-portable plan.)

## 6. What does NOT port

| GitHub thing | Replacement on Gitea |
|---|---|
| GitHub App tokens (`pupabobas`, `APP_ID`/`APP_PRIVATE_KEY`) | plain user API tokens (section 2) |
| `GITHUB_TOKEN` per-workflow principal | Gitea Actions provides a same-named token for CI, but the box never uses it |
| Copilot review gate | box reviewer identity: `can_review()` / `approve_pr()` with `WGMESH_REVIEWER_PAT`; CI + sanitise walls stay authoritative |
| Search API (`/search/issues`) | adapter lists closed pulls and applies the same exact-title resolution regex |
| Check-runs API | commit-status API (`/commits/{sha}/status`); fail-closed semantics preserved (no statuses ≠ green) |
| Label writes by name | adapter resolves name → numeric id internally; callers still use names |

## 7. End-to-end verification checklist (local Forgejo)

Run once per adapter change; the stubbed conformance suite
(`pytest tests/conformance/ -q`) is the always-on contract, this checklist is
the live proof.

1. `docker compose -f tests/conformance/docker-compose.gitea.yml up -d`,
   bootstrap users/token/repo per the comments in that file.
2. `GITEA_LIVE=1 GITEA_TOKEN=... GITEA_REPO=conformance/conformance
   .venv/bin/python -m pytest tests/conformance/ -q` — live contract tests
   pass (issue + label round-trip, resolution-PR negative, branch lookup).
3. **Issue → spec PR:** create an issue labeled `needs-triage`; run the box
   in `spec-only` with `FORGE_KIND=gitea` → spec branch pushed, spec PR
   opened, labels swapped (`needs-triage` → `copilot-triaging`).
4. **Review:** with `WGMESH_REVIEWER_PAT` set, `can_review()` is true; box
   approves the PR as the reviewer identity; `list_pr_approvals` shows the
   reviewer login.
5. **Checks gate:** with no CI configured, `pr_checks_green` is **False**
   (fail-closed); after `.gitea/workflows/ci.yml` runs green on the PR head,
   it flips True.
6. **Merge:** in `live` mode the box squash-merges; issue's
   `has_merged_resolution_pr` flips True for the exact spec/impl title and
   stays False for loose mentions.
7. Record date + Forgejo version of the last successful run below.

| Date | Forgejo | Result |
|---|---|---|
| _pending_ | 11.0.3 (pinned) | checklist not yet executed end-to-end |
