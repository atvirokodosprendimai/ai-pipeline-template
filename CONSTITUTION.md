# Project Constitution

> **Version:** 3.0.0 | **Last Updated:** 2026-06-19
> **Project Type:** GitHub Actions automation pipeline

This constitution defines the enforceable rules for the ai-pipeline-template project.
Every rule includes a severity level, a machine-checkable pattern or check command,
and evidence from the current codebase. Rules are grouped by domain.

**Severity Levels:**
- **L1 (Critical):** Must never be violated. Blocks merge.
- **L2 (Important):** Should not be violated without documented justification.
- **L3 (Advisory):** Best practice. Violations flagged as warnings.

---

## Foundational Principle: Andon

> **If a step is important enough to exist, it is important enough to stop on failure.
> If a step is not important enough to stop on failure, it must not exist.**

There is no middle ground. No silent errors. No swallowed warnings. No `|| true` without a loud signal.

Every step in every workflow and script falls into exactly one of two categories:

| Category | On failure | Implementation |
|----------|-----------|----------------|
| **Essential** | Stop. Escalate. Make it visible. | `set -e` catches it, or explicit `if ! cmd; then echo "::error::..."; exit 1; fi` |
| **Not essential** | Remove the step entirely. | If you wouldn't stop the pipeline for it, don't run it. |

This eliminates the gray area where steps "sort of matter" and failures are logged but ignored. That gray area is where silent corruption lives.

**Applying Andon to loops:** Healing loops process multiple items. A single item failure should not stop processing of other items — but it MUST be counted, logged, and escalated when thresholds are breached (see SEC-7: Circuit Breaker). The loop continues; the failure is never silent.

```yaml
# Andon in a loop:
if ! gh issue edit "$num" ...; then
  echo "::warning::Failed to heal issue #${num}"
  ERRORS=$((ERRORS + 1))          # counted
  jq -nc '...' >> "$AUDIT_LOG"    # logged
fi
# Circuit breaker checks ERRORS threshold after each step
```

**This principle supersedes QUAL-5.** The old "soft-fail" rule permitted `|| true`. Under Andon, every suppressed failure must produce a visible signal (warning annotation + error counter + audit entry). Silent suppression is prohibited.

---

## Product Values

These rules bind every product the autonomous company builds — present (wgmesh) and future — not only this control-plane repo's engineering. The pipeline is the company's brain; its constitution is the company's constitution. The monetization boundary is drawn at the **deployment layer, not the feature layer**: shipped software is free and whole; money attaches only to the service the company operates on a user's behalf.

### PROD-1: Components ship AGPL with full functionality

```yaml
level: L1
check: "Every shipped product component (daemon, CLI, dashboard, library) is licensed AGPL (or a compatible strong copyleft) and delivers full functionality. No feature is reserved for, or unlocked by, payment."
scope: "seeded product repos (TARGET_REPO, e.g. atvirokodosprendimai/wgmesh)"
message: "Product components must be AGPL and feature-complete. There is no 'pro' build, no withheld tier. The AGPL build is the whole product."
```

AGPL is load-bearing, not incidental: it closes the SaaS loophole, so the managed layer running modified components must offer its source. This makes "paid hosting" reinforce openness instead of eroding it.

### PROD-2: No component may gate functionality

```yaml
level: L1
check: "No shipped component gates functionality on payment, license key, account state, trial/time limit, or remote authorization. Self-hosted software runs fully, offline, indefinitely. Enforced by the no_component_paywall Langfuse judge wired into decide_gate and the .github/workflows/values-audit.yml CI gate (company/scripts/values-audit.sh)."
scope: "seeded product repos + pipeline spec/impl gates"
pattern: "trial_expired|expire-trial|kill.?switch|license.?check|feature.?gate"
message: "A component must never gate functionality on payment, license key, account state, trial/time limit, or remote authorization. No phone-home, no remote disable, no kill-switch in shipped software."
```

Evidence: `atvirokodosprendimai/wgmesh#766` ("Build trial expiration paywall: upgrade modal + mesh pause on day 14") specified an `expire-trial` API and mesh daemons that **stop routing when the account expires** — a license kill-switch in AGPL software a user runs on their own machine. It was generated autonomously with no human intent and no rule vetoing it. The `no_component_paywall` judge and the values-audit CI gate are the practiced enforcement that now rejects this class of work to `needs-human`.

### PROD-3: Monetize the managed-service layer only

```yaml
level: L1
check: "Monetization (billing, trials, subscriptions) attaches only to the managed-service layer (cloudroof.eu: hosting, managed ingress, support, SLA). A trial or subscription ending may cease company-operated service for that account; it may never alter, disable, or degrade software the user runs themselves."
scope: "company/system-prompt.md funnel stages + fn:billing/fn:gtm work"
message: "Revenue attaches to operation, never to withholding capability. 'Open product, paid hosting' — not open-core."
```

The system-prompt funnel (Stage 3 "billing live", Stage 5 "invoice paid") and `fn:billing`/`fn:gtm` are re-scoped to the managed layer so the loop pursues revenue without gating components.

### PROD-4: Component vs managed-service-layer boundary

```yaml
level: L1
check: "Plans, specs, and code distinguish a 'component' (anything shipped to or run on a user's machine, or constituting the product's core capability) from the 'managed-service layer' (infrastructure the company operates on the user's behalf). The boundary decides where monetization may attach."
scope: "seeded product repos + planning/spec artifacts"
message: "Component = never paywalled. Managed-service layer = the only paid surface. #766's mesh-pause-on-expiry is the worked counter-example: stopping a company-operated node is allowed; disabling the user's own daemon is not."
```

A cloudroof.eu trial ending stops cloudroof-operated nodes/ingress for that account. The wgmesh binary the user self-hosts keeps routing unconditionally — it never phones home, checks a license, or reads account state.

---

## Security

### SEC-1: Secrets via env blocks only

```yaml
level: L1
pattern: "\\$\\{\\{\\s*secrets\\."
scope: ".github/workflows/*.yml"
check: "All secrets.* references appear inside env: blocks, never in run: string interpolation"
message: "Secrets must flow through env: blocks. Never hardcode or interpolate secrets directly in run: steps."
```

All workflow files reference `${{ secrets.PUSH_TOKEN }}` and `${{ secrets.OPENROUTER_API_KEY }}` exclusively via `env:` mappings. Hardcoded credentials are unconditionally prohibited.

### SEC-2: Sanitise all published content

```yaml
level: L1
check: "Every step that writes to issues, PRs, or commits must pipe content through company/scripts/sanitise.sh"
scope: ".github/workflows/*.yml"
pattern: "sanitise\\.sh"
message: "All user-facing content (issues, PRs, commit messages) must pass through sanitise.sh before publishing. Steps must skip on sanitisation failure."
```

`pipeline-health.yml` and `observation-loop.yml` both invoke sanitisation on every user-facing publish path, with multiple call sites per workflow. Sanitisation failure must cause the publish step to be skipped, never bypassed.

### SEC-3: Event context through env only

```yaml
level: L1
pattern: "github\\.event\\.|inputs\\."
scope: ".github/workflows/*.yml"
check: "github.event.* and inputs.* values are assigned to env: vars, never interpolated inside run: blocks"
message: "Event context (github.event.*, inputs.*) must be passed through env: to prevent injection. Never interpolate directly in run: blocks."
```

Evidence at `pipeline-health.yml:66-67` and `loop-automerge.yml:24-26`. Direct interpolation of event payloads in `run:` blocks enables arbitrary code injection via crafted issue titles or PR bodies.

### SEC-4: Explicit minimal permissions

```yaml
level: L1
pattern: "^permissions:"
scope: ".github/workflows/*.yml"
check: "Every workflow file declares a top-level permissions: block with least-privilege scopes"
message: "Workflows must declare an explicit minimal permissions: block. Never rely on default token permissions."
```

All 9 workflow files declare explicit `permissions:` blocks. Omitting permissions silently grants the default token broad access, violating least-privilege.

### SEC-5: textContent for untrusted data in dashboard

```yaml
level: L2
pattern: "innerHTML"
scope: "**/*.html"
exclude: "Static HTML structure only (no external data)"
check: "No innerHTML assignment with data sourced from API responses or state files"
message: "Dashboard must use textContent for untrusted data. innerHTML with external content enables XSS."
```

The dashboard (in the chimney companion repo) uses `textContent` exclusively for dynamic data rendering. Any introduction of `innerHTML` with API-sourced or state-file data must be rejected. This rule applies to any HTML dashboard files in this repo or its companions.

### SEC-6: Secure external links

```yaml
level: L2
pattern: 'target="_blank"'
scope: "**/*.html"
check: 'All target="_blank" links include rel="noopener noreferrer"'
message: 'Links with target="_blank" must include rel="noopener noreferrer" to prevent reverse tabnapping.'
```

Evidence at chimney `docs/pipeline.html:368,448`. Omitting `rel="noopener noreferrer"` on blank-target links allows the opened page to access `window.opener` and redirect the parent.

### SEC-7: Circuit breaker on healing loops

```yaml
level: L2
check: "Healing loops enforce max 10 creates and 5 errors per run before breaking"
scope: ".github/workflows/pipeline-health.yml"
pattern: "circuit.breaker|max_creates|max_errors"
message: "Healing loops must implement a circuit breaker (10 creates / 5 errors per run) to prevent runaway automation."
```

Evidence at `pipeline-health.yml:189-209`. Without a circuit breaker, a misconfigured healing rule can create unbounded issues or PRs in a single run.

---

## Architecture

### ARCH-1: State files in company/

```yaml
level: L1
check: "All persistent state files (JSON, JSONL, YAML) reside under company/. No state files in root or .github/"
scope: "**/*.{json,jsonl,yaml,yml}"
exclude: "package.json, package-lock.json, tsconfig.json, .github/**/*.yml, .start/**"
message: "State files must live in company/. Root and .github/ are reserved for configuration and workflow definitions."
```

7 state files reside in `company/`. Scattering state across the repo creates ambiguity about which files are safe to modify programmatically.

### ARCH-2: Scripts in company/scripts/

```yaml
level: L1
check: "Shell scripts live in company/scripts/. Workflows call scripts, not inline >20-line bash"
scope: ".github/workflows/*.yml"
pattern: "company/scripts/"
message: "Shell logic must be extracted to company/scripts/. Workflow run: blocks exceeding 20 lines must be refactored into scripts."
```

8 scripts in `company/scripts/`. Inline bash in workflow YAML is untestable, unlintable, and difficult to review. Scripts enable reuse and local testing.

### ARCH-3: Spec directory structure

```yaml
level: L1
check: "Specs follow .start/specs/NNN-<name>/ with README.md, requirements, solution docs"
scope: ".start/specs/**"
pattern: "^\\d{3}-"
message: "Specs must follow the .start/specs/NNN-<name>/ convention with README, requirements, and solution documents."
```

Spec 001 establishes the canonical structure. Consistent spec layout enables automated discovery and status tracking across the planning pipeline.

### ARCH-4: Automated PRs must self-merge (with review and guardrails)

```yaml
level: L1
check: "Workflows creating automated PRs include a self-merge step via company/scripts/pr-review-merge.sh. The script enforces: Copilot review (poll + timeout), author allowlist, size limit, security keyword scan, and CI status check. No path-based restrictions — the guardrail system protects the goal, not specific file paths."
scope: ".github/workflows/*.yml"
pattern: "pr-review-merge\\.sh"
message: "Automated PRs must self-merge through pr-review-merge.sh which enforces review + guardrails. The old data-path scoping is replaced by comprehensive guardrails (author, review, size, keywords, CI)."
```

Evidence at `pipeline-health.yml` and `observation-loop.yml`. Self-merge is a necessary workaround for the GitHub App limitation (reviews don't trigger workflow events). Protection comes from the guardrail system: Copilot review required (never merge without review), author must be an approved bot, security keywords scanned, CI must pass, size limits enforced, circuit breaker on errors. Path-based scoping was the compensating control before guardrails existed; the guardrails now protect the goal directly.

### ARCH-5: Cross-repo via TARGET_REPO env var

```yaml
level: L1
check: "Cross-repo operations reference TARGET_REPO env var, not hardcoded owner/repo strings"
scope: ".github/workflows/*.yml"
pattern: "TARGET_REPO"
message: "Cross-repo operations must use the TARGET_REPO env var (owner/repo format). No inline hardcoding of repository references."
```

Evidence at `pipeline-health.yml:24`. Hardcoded repo references break forks and make the template non-portable.

### ARCH-6: Concurrency on stateful workflows

```yaml
level: L2
check: "Scheduled and stateful workflows declare concurrency: with cancel-in-progress: false"
scope: ".github/workflows/*.yml"
pattern: "concurrency:"
message: "Scheduled/stateful workflows must set concurrency with cancel-in-progress: false to prevent data corruption from overlapping runs."
```

Evidence at `pipeline-health.yml:19-21`. Stateful workflows that cancel in-progress runs risk partial state writes and corrupted JSON files.

### ARCH-7: Automated PR branch naming

```yaml
level: L2
check: "Automated PR branches follow <workflow-prefix>/{date}-{run_id} naming convention"
scope: ".github/workflows/*.yml"
pattern: "\\w+/\\$\\{.*date.*\\}-\\$\\{.*run_id"
message: "Automated PR branches must use <workflow-prefix>/{date}-{run_id} naming for traceability and conflict avoidance."
```

Evidence at `observation-loop.yml:380` and `pipeline-health.yml:728`. Predictable branch naming enables automated cleanup and audit trail correlation.

### ARCH-8: PUSH_TOKEN for repo writes

```yaml
level: L2
check: "All commit-creating workflows authenticate with PUSH_TOKEN (PAT), not GITHUB_TOKEN"
scope: ".github/workflows/*.yml"
pattern: "PUSH_TOKEN"
message: "Workflows writing to the repo must use PUSH_TOKEN (a PAT) instead of GITHUB_TOKEN. GITHUB_TOKEN commits do not trigger downstream workflows."
```

All commit-creating workflows use `PUSH_TOKEN`. Commits made with `GITHUB_TOKEN` are intentionally excluded from triggering subsequent workflow runs, breaking pipeline chains.

### ARCH-9: State file recovery and idempotency

```yaml
level: L2
check: "State files are git-tracked so corruption is recoverable via git checkout. Healing workflows must be idempotent (safe to re-run on the same input without side effects)."
scope: ".github/workflows/*.yml, company/*.json, company/*.jsonl"
message: "State files must be git-tracked for recovery. Healing workflows must be idempotent — re-running on the same state must not create duplicate issues or corrupt counters."
```

State files are committed via PR after each cycle, providing git-based rollback. Idempotency is enforced through retry trackers (skip issues already in cooldown), duplicate detection (fuzzy title matching before issue creation), and the circuit breaker (cap actions per run). A corrupted `pipeline-health-state.json` can be recovered with `git checkout main -- company/pipeline-health-state.json`.

---

## Code Quality

### QUAL-1: Bash strict mode

```yaml
level: L1
pattern: "set -euo pipefail"
scope: "company/scripts/*.sh"
check: "Every shell script starts with #!/usr/bin/env bash and set -euo pipefail"
message: "Shell scripts must begin with #!/usr/bin/env bash and set -euo pipefail. This catches undefined variables, pipe failures, and unexpected errors."
```

All 8 scripts follow this pattern. Without strict mode, scripts silently continue past failures, producing corrupt state or partial results.

### QUAL-2: Atomic file writes with jq

```yaml
level: L1
check: "All jq write operations that modify state files must use the temp-file-then-mv pattern: jq ... > /tmp/tmpfile && mv /tmp/tmpfile \"$TARGET\". The && guard ensures mv only runs if jq succeeds."
scope: ".github/workflows/*.yml, company/scripts/*.sh"
message: "jq mutations must write to a temp file then mv atomically. Direct > redirect to the source file risks truncation on failure."
```

Evidence at 7 locations in `pipeline-health.yml`. Writing jq output directly back to the input file (`jq '.x' f.json > f.json`) truncates the file before jq reads it.

### QUAL-3: Dual-platform date arithmetic

```yaml
level: L1
check: "Date arithmetic uses GNU date -d with BSD date -v fallback (or equivalent dual-platform pattern)"
scope: ".github/workflows/*.yml, company/scripts/*.sh"
pattern: "date -d|date -v"
message: "Date arithmetic must support both GNU (date -d) and BSD (date -v) variants. GitHub runners use GNU, local macOS uses BSD."
```

Evidence at `pipeline-health.yml:78-82`. Scripts that assume GNU-only `date` flags break on macOS development environments and vice versa.

### QUAL-4: Conventional commit format

```yaml
level: L1
check: "Commit messages follow <type>: <description> format"
pattern: "^(feat|fix|docs|test|chore|perf|ci|heal|loop|merge|refactor): "
scope: "git log"
message: "Commits must follow conventional format: <type>: <description>. Valid types: feat, fix, docs, test, chore, perf, ci, heal, loop, merge, refactor."
```

Git history confirms consistent use. Conventional commits enable automated changelog generation and semantic version bumping.

### QUAL-5: Andon on failure (no silent errors)

```yaml
level: L1
check: "Every failure in a workflow or script produces a visible signal: ::error:: or ::warning:: annotation, error counter increment, and audit log entry. Bare || true is prohibited. Bare 2>/dev/null without a following error handler is prohibited."
scope: ".github/workflows/*.yml, company/scripts/*.sh"
pattern: "\\|\\| true"
message: "Andon: no silent failures. Every caught error must produce a visible signal (annotation + counter + audit). If a step isn't worth signaling on failure, remove it."
```

**Implements the Andon principle.** This is an L1 rule — silent error suppression is as dangerous as no error handling at all. The pattern `|| true` and bare `2>/dev/null` hide expired tokens, permission denials, and state corruption behind a green CI check.

The only acceptable error suppression pattern:
```bash
if ! gh issue edit "$num" 2>/dev/null; then
  echo "::warning::Failed to edit issue #${num}"
  ERRORS=$((ERRORS + 1))
  # audit log entry
fi
```

### QUAL-6: JSON construction via jq

```yaml
level: L2
pattern: "jq -n --arg"
scope: "company/scripts/*.sh"
check: "JSON payloads are constructed with jq -n --arg/--argjson, never string interpolation"
message: "JSON must be constructed with jq -n --arg/--argjson. String interpolation breaks on special characters and is vulnerable to injection."
```

Evidence in `collect-*.sh` scripts. Shell variable interpolation into JSON strings breaks on quotes, newlines, and backslashes.

### QUAL-8: State file schema validation

```yaml
level: L2
check: "State files are validated for required keys and correct types after mutation. A jq query asserting expected structure must follow every state file write."
scope: ".github/workflows/*.yml, company/scripts/*.sh"
message: "Mutated state files must be validated for required keys and types. Structurally valid JSON with missing keys or wrong types corrupts downstream consumers."
```

Atomic writes (QUAL-2) prevent truncation, but don't catch semantic corruption. A state file missing `last_check` or with `checks_run` as a string instead of number passes jq syntax checks but breaks the dashboard and observation loop. Validate after write.

### QUAL-7: Manual-only label check

```yaml
level: L2
pattern: "manual-only"
scope: ".github/workflows/pipeline-health.yml"
check: "manual-only label is checked before any healing action to allow human override"
message: "The manual-only label must be checked before healing actions. This provides an escape hatch for issues that require human intervention."
```

4 check steps in `pipeline-health.yml`. Without this gate, automation may repeatedly attempt to heal issues that require human judgment.

---

## Testing

### TEST-1: Cleanup trap on exit

```yaml
level: L1
pattern: "trap cleanup EXIT"
scope: "company/scripts/test-*.sh, company/scripts/e2e-*.sh"
check: "E2E and integration test scripts register trap cleanup EXIT to tear down all test artifacts"
message: "Test scripts must register trap cleanup EXIT. Leaked test artifacts (branches, issues, PRs) pollute the target repo."
```

Both test scripts register cleanup traps. Without cleanup, failed test runs leave orphaned branches, issues, and PRs that require manual removal.

### TEST-2: Structured PASS/FAIL output

```yaml
level: L1
pattern: "PASS|FAIL"
scope: "company/scripts/test-*.sh, company/scripts/e2e-*.sh"
check: "Tests use PASS/FAIL counters with structured output and exit 1 on any failure"
message: "Test scripts must track PASS/FAIL counts, print structured results, and exit 1 on failure. Silent failures hide regressions."
```

Both test scripts implement pass/fail counters with summary output. Unstructured test output makes CI failures difficult to diagnose from the GitHub Actions log.

### TEST-3: Pre-flight validation

```yaml
level: L2
check: "Test scripts validate required tools (gh, jq, etc.) and env vars before executing any test logic"
scope: "company/scripts/test-*.sh, company/scripts/e2e-*.sh"
pattern: "command -v|which"
message: "Tests must validate pre-flight requirements (tools, env vars) before executing. Failing mid-run with 'command not found' wastes CI minutes."
```

Evidence at both test scripts around lines 59-66. Early validation produces a clear, actionable error message instead of a cryptic failure deep in the test run.

### TEST-4: Cutoff override for E2E testability

```yaml
level: L2
check: "pipeline-health workflow exposes cutoff_override_minutes as a workflow_dispatch input"
scope: ".github/workflows/pipeline-health.yml"
pattern: "cutoff_override_minutes"
message: "The pipeline-health workflow must expose cutoff_override_minutes as a dispatch input so E2E tests can trigger healing without waiting for real staleness."
```

Evidence at `pipeline-health.yml:7-11`. Without this override, E2E tests would need to wait for the real staleness window (hours/days) before healing triggers.

### TEST-5: Configurable polling with timeout

```yaml
level: L3
pattern: "MAX_ATTEMPTS|POLL_INTERVAL"
scope: "company/scripts/test-*.sh, company/scripts/e2e-*.sh"
check: "Polling loops use configurable interval and max attempts with a timeout FAIL"
message: "Polling loops must have configurable interval and max attempts. Unbounded polling hangs CI runners indefinitely."
```

Evidence at both test scripts around lines 20-21. Hardcoded poll intervals and unbounded retries cause unpredictable CI run times and potential runner exhaustion.

---

## Amendment Process

- **Adding rules:** New rules require a PR with codebase evidence. No aspirational rules — document what's practiced.
- **Changing severity:** L1↔L2 changes require documented justification in the PR body.
- **Removing rules:** Removal requires migration notes explaining what replaces the rule or why it's no longer needed.
- **Versioning:** Major version bump (2.0.0) when L1 rules change. Minor bump (1.x.0) for L2/L3 additions or modifications.
- **Exceptions:** Temporary exceptions to L2/L3 rules can be documented inline with `<!-- EXCEPTION: reason, expires YYYY-MM-DD -->`.

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-22 | Initial constitution with 27 rules from codebase discovery |
| 1.1.0 | 2026-03-22 | Address issue #65: fix QUAL-5 tension, scope ARCH-4, add QUAL-8/ARCH-9, add amendment process |
| 1.2.0 | 2026-03-22 | Add Andon principle as foundational rule. Upgrade QUAL-5 to L1: no silent errors, every failure must signal. Remove loop-automerge.yml (PR #67) |
| 2.0.0 | 2026-03-22 | ARCH-4: replace path-based scoping with guardrail-based protection (pr-review-merge.sh). The goal is protected, not the file paths. L1 rule changed → major version bump. |
| 3.0.0 | 2026-06-19 | Add Product Values domain (PROD-1..4, all L1): components ship AGPL + full functionality, no component paywall, monetize the managed-service layer only. Motivated by autobox-generated wgmesh #766 (trial kill-switch in AGPL daemon). New L1 rules → major version bump. |
