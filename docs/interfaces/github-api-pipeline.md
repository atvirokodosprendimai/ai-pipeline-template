# GitHub API — Pipeline Integration

> **Category:** External Interface
> **Service:** GitHub REST API (via `gh` CLI and chimney proxy)
> **Last Updated:** 2026-03-22
> **Status:** Active

## Overview

The pipeline self-healing system and its companion dashboard both depend on the
GitHub REST API. Two distinct access paths exist:

1. **Direct (`gh` CLI)** — The `pipeline-health.yml` GitHub Actions workflow
   uses `gh` commands to read, create, edit, and close issues and PRs on a
   target repository. All mutations happen inside the workflow run.
2. **Proxied (`/api/github`)** — The chimney service exposes a caching reverse
   proxy at `/api/github`. The pipeline dashboard (a static HTML page) fetches
   read-only data through this proxy to avoid client-side token management and
   to reduce GitHub API consumption.

## Authentication

### Workflow (GitHub Actions)

| Token | Env var | Scope | Purpose |
|-------|---------|-------|---------|
| Personal Access Token (PAT) | `PUSH_TOKEN` (Actions secret) | `repo` | Cross-repo operations on the target repo (issue/PR CRUD, contents read, push branches, create/merge PRs) |
| Default Actions token | `GITHUB_TOKEN` | Per-workflow permissions block | Same-repo checkout, read actions |

The workflow sets `GH_TOKEN` to `PUSH_TOKEN` for every step that calls `gh`,
giving the CLI cross-repo access. The `permissions:` block at the top of the
workflow grants `contents: write`, `issues: write`, `pull-requests: write`, and
`actions: read`.

### Chimney proxy

Chimney reads a GitHub PAT from its runtime environment (flag or env var) and
attaches it as a `Bearer` token on every upstream request. Dashboard clients
never see or handle a token.

## API Endpoints Used

### Self-healing workflow (`pipeline-health.yml`)

All calls target `$TARGET_REPO` (currently `atvirokodosprendimai/wgmesh`).

#### Issues

| Operation | CLI command | Fields / flags | Purpose |
|-----------|-------------|----------------|---------|
| List stale `needs-triage` | `gh issue list --state open --label "needs-triage" --limit 50 --json number,title,createdAt,labels` | `--jq` filters by `createdAt < cutoff` (24 h) | Find issues stuck at triage |
| List stale `copilot-triaging` | `gh issue list --state open --label "copilot-triaging" --limit 50 --json number,title,createdAt,labels` | `--jq` filters by `createdAt < cutoff` (48 h) | Find issues stuck in copilot triage |
| List `needs-human` | `gh issue list --state open --label "needs-human" --limit 50 --json number,title,labels` | All open, no time filter | Candidates for auto-close |
| Edit (remove label) | `gh issue edit <n> --remove-label <label>` | | First half of label-toggle healing |
| Edit (add label) | `gh issue edit <n> --add-label <label>` | 2 s sleep between remove and add | Second half of label-toggle healing |
| Create (escalation) | `gh issue create --title "[needs-human] ..." --body "..." --label "needs-human"` | Body passes through `sanitise.sh` | Escalation when retries exhausted |
| Create (circuit breaker) | `gh issue create --title "[needs-human] Pipeline self-healing circuit breaker triggered" --body "..." --label "needs-human"` | | Safety valve when per-run limits hit |
| Close (fulfilled) | `gh issue close <n> --comment "Resolved by self-healing: ..."` | Comment passes through `sanitise.sh` | Auto-close needs-human when resolution signals detected |

#### Pull requests

| Operation | CLI command | Purpose |
|-----------|-------------|---------|
| List open spec PRs | `gh pr list --state open --search "spec: Issue #<n>" --json number` | Skip healing if spec PR already in flight |
| List open impl PRs | `gh pr list --state open --search "impl: Issue #<n>" --json number` | Skip healing if impl PR already in flight |
| List stale `approved-for-build` | `gh pr list --state open --label "approved-for-build" --limit 50 --json number,title,updatedAt,labels` | Find PRs stuck awaiting build (24 h cutoff) |
| Edit (toggle label) | `gh pr edit <n> --remove-label / --add-label "approved-for-build"` | Re-trigger goose-build workflow |
| Create (state commit) | `gh pr create --title "heal: pipeline health check ..." --base main` | Commit updated state files |
| Merge (implicit) | Self-merging PR via push + create | State lands on `main` after review |

#### REST API (non-CLI)

| Operation | Endpoint | Purpose |
|-----------|----------|---------|
| Issue timeline | `gh api repos/<owner>/<repo>/issues/<n>/timeline` | Check for cross-referenced merged PRs (resolution signal for needs-human) |
| Repo contents | `gh api repos/atvirokodosprendimai/wgmesh/contents/CLAUDE.md` | Fetch CLAUDE.md to evaluate dogfood funnel signal (checks for Architecture and Build sections) |

### Dashboard (via chimney proxy at `/api/github`)

The dashboard is a static HTML page that calls chimney's `/api/github` prefix.
Chimney forwards requests to `https://api.github.com/repos/{owner}/{repo}/...`
and caches the responses.

| Dashboard call | Proxied GitHub endpoint | Data used |
|----------------|------------------------|-----------|
| `/{repo}/issues?state=open&per_page=100` | `GET /repos/{owner}/{repo}/issues` | Kanban board columns (needs-triage, copilot-triaging, approved-for-build, needs-human) |
| `/{repo}/pulls?state=closed&per_page=10&sort=updated&direction=desc` | `GET /repos/{owner}/{repo}/pulls` | Merged PRs column |
| `/{repo}/contents/company/loop-state.json` | `GET /repos/{owner}/{repo}/contents/company/loop-state.json` | Observation loop status |
| `/{repo}/contents/company/costs.json` | `GET /repos/{owner}/{repo}/contents/company/costs.json` | Cost / runway panel |
| `/{repo}/contents/company/pipeline-health-state.json` | `GET /repos/{owner}/{repo}/contents/company/pipeline-health-state.json` | Self-healing stats, funnel signals |

## Rate Limits

### Workflow

The `gh` CLI handles rate-limit retries internally; the workflow does not
inspect `X-RateLimit-Remaining` headers.

Estimated calls per run:

| Scenario | Approximate API calls |
|----------|-----------------------|
| Clean run (no stale issues) | ~7 (4 list queries + 1 timeline/contents check + state PR) |
| Full healing run (all checks active) | ~37 (lists + per-issue edits with 2-call label toggles + escalation creates + timeline checks + state PR) |

The workflow runs every 2 hours (`0 */2 * * *`), yielding a worst-case of
~444 calls/day — well within the 5,000/hour PAT limit.

### Circuit breaker

A per-run circuit breaker trips when either condition is met:

- 10 or more issues created in a single run
- 5 or more errors accumulated

When tripped, all remaining healing steps are skipped and a `needs-human` issue
is created to alert operators.

### Chimney proxy

Chimney caches responses to reduce upstream calls:

| Path pattern | TTL |
|--------------|-----|
| `/actions/runs` | 30 s |
| `/pulls` with `state=closed` | 5 min |
| `/issues` | 2 min |
| All other paths (including `/contents/`) | 30 s |

Revalidation uses **ETag-based conditional requests** (`If-None-Match`). A
`304 Not Modified` response refreshes the TTL without transferring the body.

Cache tiers (checked in order):

1. **Dragonfly** (Redis-compatible, persistent) — primary cache
2. **In-memory map** — fallback when Dragonfly is unavailable

Chimney also normalizes query parameters (sorted, allowlist-filtered) to prevent
cache-bust via parameter reordering. Allowed query parameters:
`state`, `per_page`, `page`, `sort`, `direction`, `since`, `until`, `status`,
`sha`, `ref`, `path`.

## Data Mapping

### Workflow state files

| File | Written by | Read by | Format |
|------|-----------|---------|--------|
| `company/pipeline-health-state.json` | Workflow (every run) | Dashboard, workflow (next run) | JSON — `last_check`, `checks_run`, `issues_healed_total`, `retry_tracker`, `funnel_signals`, `last_run_summary` |
| `company/audit-log.jsonl` | Workflow (append per action) | Operators (manual review) | JSONL — `timestamp`, `run_id`, `action`, `issue_number`, `target_repo`, `reason`, `outcome`, `retry_count` |
| `company/loop-state.json` | Observation loop | Dashboard, workflow (needs-human signal) | JSON — `last_run`, `run_count` |
| `company/costs.json` | External | Dashboard, workflow (needs-human signal) | JSON — `runway.available_capital` |

### Label-to-column mapping (dashboard)

| GitHub label | Dashboard column |
|--------------|-----------------|
| `needs-triage` | Needs Triage |
| `copilot-triaging` | Copilot Triaging |
| `approved-for-build` | Approved for Build |
| `needs-human` | Needs Human |
| _(closed PR with merged_at)_ | Merged |

## Error Handling

### Workflow

- Every `gh` call is guarded with `|| { local_errors=$((local_errors + 1)); true; }` or `|| true` to prevent step failure from aborting the run.
- Errors accumulate in `$ERRORS` and feed into the circuit breaker.
- All issue/comment bodies pass through `company/scripts/sanitise.sh` before
  submission; if sanitisation fails, the action is skipped and an error is
  counted.
- Stale-cache fallback: when no healing is possible (cooldown active, retries
  exhausted), the workflow skips the issue and logs it.

### Chimney proxy

- **Upstream failure with stale cache:** If the GitHub API returns an error but
  a cached entry exists, chimney serves the stale cached response rather than
  propagating the error to the dashboard.
- **Upstream 5xx:** Logged with an error-status OpenTelemetry span; stale cache
  served if available.
- **Body size limit:** Responses are capped via `io.LimitReader` to prevent
  memory exhaustion from unexpectedly large payloads.
- **Path traversal rejection:** Paths containing `..` are rejected with
  `400 Bad Request` to prevent SSRF.

## Security Considerations

- **Token isolation:** `PUSH_TOKEN` is stored as a GitHub Actions encrypted
  secret and never logged. Chimney receives its token via environment variable,
  not hardcoded in source.
- **Sanitisation gate:** All user-visible text (issue titles, bodies, comments)
  passes through `sanitise.sh` before submission to prevent injection of
  unexpected content.
- **SSRF prevention:** Chimney rejects proxy paths containing `..` and only
  forwards requests matching discovered repos (in org mode) or the configured
  single repo.
- **Query allowlist:** Chimney only forwards a fixed set of query parameters to
  GitHub, preventing token quota exhaustion via arbitrary parameter injection.
- **No client-side tokens:** The dashboard never handles GitHub tokens; all API
  access is mediated by chimney.
- **Known limitation:** GitHub Apps do not trigger `pull_request_review` events
  on their own PRs. This affects workflows that rely on review events for
  automation. See `docs/solutions/integration-issues/github-app-reviews-dont-trigger-workflows.md`.

## Related Documentation

| Document | Path |
|----------|------|
| Self-healing workflow | `.github/workflows/pipeline-health.yml` |
| Chimney proxy (Go source) | `chimney/main.go` (TTL: lines 455-468, proxy handler: lines 520-715) |
| Dashboard | `chimney/docs/pipeline.html` (fetch helpers: lines 310-326) |
| GitHub App review limitation | `docs/solutions/integration-issues/github-app-reviews-dont-trigger-workflows.md` |
| Pipeline health state schema | `company/pipeline-health-state.json` |
| Audit log format | `company/audit-log.jsonl` |

## Version History

| Date | Change |
|------|--------|
| 2026-03-22 | Initial document — covers Phase 1-3 self-healing endpoints, chimney caching, and dashboard reads |
