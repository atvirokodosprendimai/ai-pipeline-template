---
tldr: Bash-native test harness that exercises the real GitHub API with structured pass/fail accounting, automatic artifact cleanup, and configurable cutoff overrides for time-sensitive scenarios
category: core
---

# Testing Infrastructure

## Target

The test framework exists to give the autonomous pipeline a way to verify its own behaviour against production GitHub state — without a staging environment, without mocks for the happy path, and without leaving behind any test debris. Every script must exit cleanly with a numeric verdict (Passed N / Failed M) so that CI can assert on the return code and humans can read the summary at a glance.

Two distinct test modes coexist:

- **E2E tests** (`test-self-healing-e2e.sh`, `test-circuit-breaker-e2e.sh`) — issue real GitHub API calls, trigger real workflow runs, and poll for real workflow conclusions. They verify the full pipeline from trigger to state file to audit log.
- **Integration tests** (`test-pr-review-merge.sh`, `test-collect-memory.sh`) — isolate individual script functions via `eval`/`awk` extraction and mock `gh` with a per-test shim, verifying behaviour without network calls.

## Behaviour

- Every script declares `PASS_COUNT=0` / `FAIL_COUNT=0` (or `PASS=0` / `FAIL=0`) at top-level and increments them via `pass()`/`fail()` helpers that write `PASS:` / `FAIL:` lines to stdout. {>> This uniform prefix enables `grep`-based CI parsing and human scanning without colour codes.}

- The final block always prints `Results: N passed, M failed` and exits 1 if `FAIL_COUNT > 0`. No test can silently absorb a failure.

- **Pre-flight validation** runs before any test artifact is created: `require_tool gh`, `require_tool jq`, and an explicit check that `GH_TOKEN` is non-empty. Any missing prerequisite aborts immediately with a clear `ERROR:` message. {>> Validation before side effects prevents partial runs that leave orphaned issues/PRs when the environment is under-provisioned.}

- **Cleanup traps** register `trap cleanup EXIT` unconditionally. The `cleanup()` function iterates arrays (`CREATED_ISSUES`, `CREATED_PRS`) accumulated during the run and closes/deletes each artifact via `gh issue close` / `gh pr close`, with `2>/dev/null || true` to suppress errors on already-closed items. E2E tests that can produce secondary escalation issues (circuit breaker) also query GitHub by label+title pattern to find and close those. {>> Traps fire on both clean exit and error exit, so a mid-run failure still triggers cleanup.}

- **Configurable poll intervals and timeouts** are declared as named readonly constants (`POLL_INTERVAL=15`, `MAX_POLL_ATTEMPTS=40`). The poll loop uses `seq 1 $MAX_POLL_ATTEMPTS`, checks `gh run view --json status,conclusion`, and breaks on `completed`. When the attempt ceiling is hit without completion, `fail` is called and the script exits 1. {>> 40 × 15 s = 10 min cap prevents tests from hanging indefinitely while remaining generous enough for slow GitHub Actions queues.}

- **Cutoff overrides for self-healing testability**: the self-healing and circuit-breaker E2E tests trigger `pipeline-health.yml` with `cutoff_override_minutes=1` via `workflow_dispatch`. This collapses the normally 24-hour stale window to 1 minute, making freshly created test issues immediately eligible for processing. {>> Without this override, stale detection could not be tested without waiting 24 hours. The override is passed as a workflow input, not an env var, so it does not bleed into production runs.}

- **Mock `gh` shim pattern** (integration tests): a per-test `create_mock_gh()` writes a bash script to `$TMPDIR/bin/gh` and prepends `$TMPDIR/bin` to `$PATH`. Each mock is a series of `if [[ "$1" == "pr" && ... ]]` guards routing to canned output. PATH is restored in the EXIT trap. {>> This lets individual guard paths (author check, file list, diff content) be exercised in isolation without GitHub credentials.}

- **Function extraction pattern** (integration tests): `eval_functions()` uses `awk` to extract named function bodies from the production script by matching function name lines and closing braces, then `eval`s them into the test shell. The `setup_test_env()` helper exports the same env vars the production script expects, including zero-value overrides for polling (`POLL_INTERVAL=0`, `POLL_MAX_ATTEMPTS=1`) to make integration tests instantaneous. {>> This avoids duplicating the script under test or maintaining a separate testable interface — the production source is the single source of truth.}

- **Assert helpers** provide structured comparison: `assert_eq` (exact match), `assert_contains` (substring via `grep -qF`), `assert_not_contains` (negated substring), `assert_le` (numeric ceiling). All increment `PASS`/`FAIL` and print labelled lines.

- **Audit log verification**: E2E tests do not just check workflow exit status — they fetch the audit log from the state-update PR branch via `gh api repos/.../contents/audit-log.jsonl?ref=<branch>`, base64-decode it, and assert that required JSON fields (`timestamp`, `action`, `run_id`) and specific action values (`circuit_breaker`, `escalate`, `guardrails_passed`) are present. {>> This verifies the observability layer, not just side effects. A workflow that acts correctly but fails to write the audit log is still a test failure.}

- **Graceful degradation coverage**: collect-memory integration tests include cases where the memory directory does not exist and where the episodic directory is empty. Both must exit 0 and return semantic content without crashing. {>> Degradation tests codify the contract that missing optional data never causes a hard failure.}

## Design

**Real API over mocks for E2E, mocks for unit logic.** The E2E tests make no attempt to stub GitHub. They create real issues and PRs, trigger real workflows, and read real state files. This is intentional: the pipeline's output is GitHub state, and the only meaningful assertion about GitHub state is GitHub's own API response. Unit-level behaviour (author checks, guardrail logic, label parsing) uses mocks because those are pure transformations of API responses.

**Test artifacts are labelled.** Every issue and PR created by E2E tests carries an `e2e-test-artifact` label. Cleanup queries by label when sweeping for secondary artifacts (escalation issues). This makes test debris discoverable even if a test crashes before its cleanup trap runs.

**Timestamped branch names prevent collisions.** Test PRs use `e2e-test/stale-build-$(date -u '+%s')` as the branch name. Multiple concurrent test runs cannot collide on the branch name.

**Circuit breaker E2E tests threshold arithmetic explicitly.** The test creates `BREAKER_CREATE_THRESHOLD + 2` (12) issues and asserts that fewer than 12 received label changes — demonstrating that the breaker halted processing partway through. The state file's `last_run_summary.actions_taken` is also checked to confirm the count is non-zero, catching a breaker that fires on the first action rather than the tenth.

**Integration tests source production code, not a copy.** The `awk` extraction in `eval_functions()` reads directly from `$REAL_SCRIPT_DIR/pr-review-merge.sh`. If the production function signature changes, the test will break immediately — which is the desired behaviour.

**Separation of concerns in summaries.** E2E tests print a structured footer including workflow run ID, issue numbers created, and threshold values alongside pass/fail counts. This makes post-mortem debugging possible from CI log output alone, without re-running the test.

## Interactions

- The self-healing E2E test exercises: issue creation, label manipulation, `workflow_dispatch` triggering, workflow run polling, state file (`pipeline-health-state.json`) reads, and audit log (`audit-log.jsonl`) validation — spanning the full [[spec - self healing - deterministic pipeline recovery]] path.
- The circuit-breaker E2E test stresses the threshold logic and escalation issue creation within [[spec - self healing - deterministic pipeline recovery]], verifying that the breaker fires without failing the workflow run itself.
- The PR review-merge integration tests exercise every guardrail (author allowlist, protected paths, size limit, security keywords, circuit breaker, manual-only label, manual push detection) defined in [[spec - pr review merge - autonomous bot pr guardrails]].
- The collect-memory integration tests verify the context assembly layer that feeds agent prompts, covering semantic-only mode, tag filtering, recency limiting, and budget truncation.
- Security keyword scanning (`secret`, `token`, `key`, `password`, `api_key`, `private_key`) is exercised as a guardrail rejection case, connecting to [[spec - security quality - constitution and enforcement]].

## Mapping

- `company/scripts/test-self-healing-e2e.sh` — E2E test for the full self-healing pipeline (T4.1): issue creation, workflow trigger, poll, state file and audit log verification
- `company/scripts/test-circuit-breaker-e2e.sh` — E2E test for circuit breaker threshold logic (T4.2): bulk issue creation, breaker fire detection, escalation issue verification
- `company/scripts/test-pr-review-merge.sh` — Integration tests for `pr-review-merge.sh`: function extraction via awk/eval, mock gh shim, 13 test cases covering every guardrail path and audit logging
- `company/scripts/test-collect-memory.sh` — Integration tests for `collect-memory.sh`: fixture-based tests for semantic/episodic modes, tag filtering, budget enforcement, and graceful degradation
