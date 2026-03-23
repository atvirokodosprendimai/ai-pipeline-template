---
tldr: Overview pull of the entire ai-pipeline-template system — maps territory for subsection pulls
status: complete
---

# Pull: AI Pipeline Template — Full System Overview

## Sources

- `.github/workflows/observation-loop.yml` — daily OODA loop: collect state, LLM assessment, act on issues
- `.github/workflows/pipeline-health.yml` — self-healing: detect stale issues, toggle labels, circuit breaker
- `.github/workflows/health-check.yml` — lightweight endpoint monitoring (15-min curl checks, auto-issue)
- `.github/workflows/copilot-triage.yml` — assigns Copilot to write specs for new issues
- `.github/workflows/spec-validation.yml` — structural checks on spec PRs, auto-approve or flag
- `.github/workflows/approve-build.yml` — spec approval flow: approved → trigger Goose build
- `.github/workflows/spec-merged-build.yml` — spec merged → assign build agent to implement
- `.github/workflows/impl-merged-close.yml` — implementation merged → close originating issue
- `.github/workflows/bot-pr-review-merge.yml` — autonomous PR review and merge for bot PRs
- `.github/workflows/copilot-undraft.yml` — auto-undraft Copilot draft PRs
- `.github/workflows/sync-labels.yml` — sync pipeline labels from definition file
- `.github/scripts/validate-spec.sh` — structural spec validation script
- `company/scripts/collect-github.sh` — GitHub API signal collector (issues, PRs, merge rate)
- `company/scripts/collect-infra.sh` — infrastructure health checker (curl endpoints)
- `company/scripts/collect-contributions.sh` — git author + dependency tracker
- `company/scripts/collect-memory.sh` — shared memory aggregator (semantic + episodic)
- `company/scripts/pr-review-merge.sh` — guardrailed autonomous PR merge (Copilot review, size limits, security scan)
- `company/scripts/sanitise.sh` — secret/PII scanner for public output
- `company/scripts/test-*.sh` — E2E and integration test scripts
- `company/system-prompt.md` — LLM operational instructions for the observation loop
- `company/loop-state.json` — funnel stage, run count, timestamps
- `company/health.json` — infrastructure endpoints to monitor
- `company/pipeline-health-state.json` — self-healing state: retry tracker, counters
- `company/metrics.json` — product/community/revenue signals
- `company/costs.json` — available capital, monthly burn
- `company/contributors.json` — contribution ledger
- `CONSTITUTION.md` — enforceable rules: security, architecture, quality, testing
- `README.md` — template documentation and quick start
- `docs/domain/pipeline-state-machine.md` — issue lifecycle state machine
- `docs/patterns/pr-review-merge.md` — PR review and merge pattern docs
- `docs/patterns/workflow-self-merge.md` — self-merge pattern docs

## Existing Specs

None found in `eidos/` (freshly initialised).

## Major Subsections

The system decomposes into 7 distinct concerns:

### 1. Observation Loop (OODA Cycle)

The beating heart of the system. Runs every 8 hours. Collects signals from GitHub, infrastructure, contributions, costs, and memory. Sends state to an LLM with a company-aware system prompt. The LLM returns a structured JSON assessment that drives issue creation/closure, funnel stage tracking, and contribution logging.

**Key files:** `observation-loop.yml`, `collect-github.sh`, `collect-infra.sh`, `collect-contributions.sh`, `collect-memory.sh`, `system-prompt.md`, `loop-state.json`

**Key behaviours:**
- Multi-repo signal collection (primary full, secondary lightweight)
- LLM assessment with structured JSON output
- Issue creation/closure based on assessment
- Assessment archival to `company/loop-history/`
- Funnel stage tracking (Foundation → Dogfood → Presence → Reachable → Pipeline → Revenue)
- Reciprocity tracking for contributors
- Public/private boundary enforcement (no secrets in public output)

### 2. Pipeline State Machine (Issue Lifecycle)

Label-driven state machine governing how issues flow from creation to merge. Each pipeline stage is a GitHub label. Issues progress: `needs-triage` → `copilot-triaging` → `spec-ready` → `approved-for-build` → `goose-implementation` → merged.

**Key files:** `copilot-triage.yml`, `spec-validation.yml`, `approve-build.yml`, `spec-merged-build.yml`, `impl-merged-close.yml`, `copilot-undraft.yml`, `docs/domain/pipeline-state-machine.md`

**Key behaviours:**
- Label transitions drive the entire pipeline (no manual orchestration)
- Copilot writes specs, Goose implements code
- Spec validation auto-approves or flags structural issues
- Human approval is a gate between spec and build
- Implementation merge auto-closes the originating issue
- Copilot draft PRs are auto-undrafted for review flow

### 3. Self-Healing (Pipeline Health)

Deterministic (no LLM) recovery system that detects stale issues and re-triggers workflows. Runs every 2 hours. Includes circuit breaker (10 creates / 5 errors), per-issue escalation (2 failures → needs-human), cooldown periods, and needs-human auto-close on resolution signals.

**Key files:** `pipeline-health.yml`, `pipeline-health-state.json`

**Key behaviours:**
- Stale detection with per-label thresholds (24h triage, 48h copilot, 24h build)
- Label toggle recovery (remove + re-apply to re-trigger workflows)
- Circuit breaker prevents runaway automation
- Escalation to needs-human after 2 consecutive failures
- Auto-close needs-human issues when resolution signals detected
- Exclusion labels: `manual-only`, `wont-do`, `needs-info`
- Audit trail to `company/audit-log.jsonl`

### 4. Autonomous PR Review and Merge

Bot-authored PRs are automatically reviewed and merged with guardrails. Copilot review is required (polled), author must be allowlisted, size limits enforced, security keywords scanned, CI must pass.

**Key files:** `bot-pr-review-merge.yml`, `pr-review-merge.sh`

**Key behaviours:**
- Poll for Copilot review with configurable timeout
- Author allowlist (copilot-swe-agent, goose, pipeline PRs)
- Size limit (default 500 lines changed)
- Security keyword scanning
- Escalation on guardrail failures (label + comment)
- All published content sanitised via `sanitise.sh`

### 5. Infrastructure Monitoring

Two layers: lightweight health checks (15-min curl) and observation loop infrastructure collection.

**Key files:** `health-check.yml`, `collect-infra.sh`, `health.json`

**Key behaviours:**
- Health check creates/updates GitHub issues on endpoint failure
- Auto-closes issues when endpoints recover
- Observation loop collects health data as part of the state snapshot
- Endpoints configured in `health.json`

### 6. Security and Quality Framework

The CONSTITUTION.md codifies 20+ enforceable rules across security, architecture, quality, and testing. Key principles: Andon (no silent failures), secrets via env blocks only, sanitisation of all published content, atomic file writes, circuit breakers.

**Key files:** `CONSTITUTION.md`, `sanitise.sh`

**Key behaviours:**
- Secret/PII detection before any public output
- Env-only secrets and event context (no run: interpolation)
- Explicit minimal permissions on all workflows
- Bash strict mode everywhere
- Atomic jq writes (temp file + mv)
- Dual-platform date arithmetic
- Conventional commit format

### 7. Testing Infrastructure

E2E and integration tests with cleanup traps, structured PASS/FAIL output, pre-flight validation, configurable polling, and cutoff overrides for testability.

**Key files:** `test-self-healing-e2e.sh`, `test-pr-review-merge.sh`, `test-collect-memory.sh`, `test-circuit-breaker-e2e.sh`

**Key behaviours:**
- Trap-based cleanup on exit (branches, issues, PRs)
- Structured PASS/FAIL counters
- Pre-flight tool/env validation
- Configurable poll intervals and timeouts
- Cutoff override for self-healing tests

## Patterns

- **Label-driven orchestration** — GitHub labels are the state machine. Transitions happen via label add/remove, which trigger workflows.
- **Andon principle** — every failure produces a visible signal (::error::/::warning::, counter increment, audit entry). No silent suppression.
- **Circuit breaker** — caps automated actions per run to prevent runaway loops.
- **Sanitisation gate** — all public-facing output passes through `sanitise.sh` before publishing.
- **Atomic state writes** — jq to temp file, then mv. Never redirect back to source.
- **Dual-platform compatibility** — GNU date -d with BSD date -v fallback everywhere.
- **PUSH_TOKEN for writes** — PAT instead of GITHUB_TOKEN so commits trigger downstream workflows.
- **Concurrency groups** — stateful workflows use cancel-in-progress: false.
- **Audit trail** — JSONL append-only log for every automated action.

## Dependencies

- **GitHub Actions** — execution platform for all workflows
- **GitHub API** — issues, PRs, labels, reviews, search
- **GitHub Copilot coding agent** — spec writing (triage) and some builds
- **Goose** — build agent for code implementation
- **OpenRouter / LLM API** — observation loop assessment
- **jq** — JSON processing in all scripts
- **curl** — API calls and health checks
- **chimney** — companion dashboard repo (pipeline.html)
- **Target product repos** — wgmesh (primary), lighthouse, etc.

## Intent Sketch

1. **The system is an autonomous OODA loop** — it observes reality (GitHub, infra, costs), orients via LLM assessment, decides via structured JSON output, and acts by creating/closing issues. The loop runs without human intervention.

2. **Issues are the unit of work** — every action flows through GitHub issues. Labels encode state. The pipeline advances issues from intent to implementation to merge automatically.

3. **Self-healing ensures forward progress** — stale issues are detected and re-triggered deterministically (no LLM), with circuit breakers and escalation to prevent runaway automation.

4. **Security is structural, not aspirational** — sanitisation, env-only secrets, minimal permissions, and the Constitution enforce security through code, not policy documents.

5. **The Andon principle governs failure handling** — every step either stops on failure (essential) or doesn't exist (not essential). No gray area. No silent errors.

6. **Bot PRs are reviewed and merged autonomously** — with guardrails (Copilot review, size limits, security scan, author allowlist) replacing human gatekeeping.

7. **The system is a template** — designed to be forked and customised via `init.sh`. Language-agnostic, LLM-provider-agnostic, agent-role-agnostic.
