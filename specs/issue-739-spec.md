# Specification: Issue #739

## Classification
feature

## Deliverables
both

## Problem Analysis

The meta-pipeline template (`ai-pipeline-template`) seeds GitHub-Action workflow files into product repos. The current seeded `impl-merged-close.yml` has two defects inherited from the problem originally identified in wgmesh#568:

1. **Test gate accepts any `func TestXxx` as proof-of-fix for bug-class issues.** The template's `close-issue` job closes the linked issue unconditionally when an `impl:` PR merges. It makes no distinction between a `type: bug` issue (where a unit-predicate test is insufficient) and a feature/chore issue (where structural tests are fine). The wgmesh product repo already has a multi-gate handler (`scripts/workflows/impl-merged-close-handler.js`) that enforces L2/L3 gates and routes bug-fix PRs to `awaiting-verification`; the template must adopt this pattern so every freshly seeded repo gets the same discipline.

2. **`awaiting-verification` is resolved only by a human comment (`verified`/`confirmed`/`fixed`).** The template's companion `verify-comment-close.yml` listens on `issue_comment` events. On the green path — e2e/integration workflow passes — a human is still required. The issue description states explicitly: "it is supposed to be automatic". The gate must be driveable by a `workflow_run` conclusion (e2e green) rather than exclusively by human text.

3. **`copilot-instructions.md` (the spec template seeded into new repos) does not instruct Goose or Copilot to add integration tests for network/critical paths.** Agents therefore default to unit tests for all bug classes.

4. **No drift-detection exists.** Gate-related workflows can diverge silently between the meta-template and seeded product repos.

The files involved are:
- `.github/workflows/impl-merged-close.yml` — direct equivalent of wgmesh's same-named file; currently auto-closes without any bug/test gates. This file is seeded verbatim to product repos by `init.sh`.
- `.github/copilot-instructions.md` — spec template seeded to new repos; missing integration-test guidance for network/critical paths
- `scripts/sync-gate-from-wgmesh.sh` — does not exist; needs to be created

## Implementation Tasks

### Task 1: Adopt multi-gate close handler in template `impl-merged-close.yml`

- **File:** `.github/workflows/impl-merged-close.yml` (modify)
- **Where:** Replace the single `Close linked issue` step in the `close-issue` job
- **What:** Mirror the wgmesh pattern:
  1. Add a `Checkout repository` step (needed so the handler script is available at runtime).
  2. Add a `Ensure verification + tests labels exist` step that idempotently creates `awaiting-verification` and `awaiting-tests` labels using `gh label create --force`.
  3. Replace the inline `Close linked issue` `actions/github-script` step with a step that calls `./scripts/workflows/impl-merged-close-handler.js` via `require()`, identical in structure to the wgmesh version.
  4. Preserve the existing `Append impl-close outcome to MentisDB` step unchanged.
- **Detail:** The handler JS file itself is created in Task 2. The workflow step must pass `{github, context, core}` to the handler. The `permissions` block already has `issues: write` and `pull-requests: read`; add `contents: read` so the checkout and `getContent` calls work. The handler must be language-agnostic: wgmesh-specific `*_test.go` detection is moved to a configurable parameter (see Task 2 detail).

### Task 2: Create language-agnostic `impl-merged-close-handler.js` for the template

- **File:** `scripts/workflows/impl-merged-close-handler.js` (create)
- **Where:** New file at repository root path `scripts/workflows/impl-merged-close-handler.js`
- **What:** Port `scripts/workflows/impl-merged-close-handler.js` from wgmesh, replacing the wgmesh-specific Go test detection with a generic multi-language variant.
- **Detail:** The handler must:
  - Export `async function handler({github, context, core})` as `module.exports`.
  - Preserve all helper exports (`extractRepoTokens`, `labelNamesOf`, `isBug`, `detectNewTestFuncs`, `STOP_WORDS`) for unit-testability.
  - Replace the Go-specific `TEST_FUNC_REGEX_ADDED` / `TEST_FUNC_REGEX_ANY` with a configurable `TEST_PATTERNS` map keyed by file glob suffix (e.g. `_test.go`, `_test.py`, `.test.js`, `.test.ts`, `.spec.js`, `.spec.ts`) each with its own `added` and `any` regex. The handler auto-detects which patterns apply based on which test-file suffixes appear in the PR diff.
  - Preserve the L2 gate (at least one new test function added), the L3 gate (repro-keyword match against new test names or PR body), the `awaiting-tests` label path when gates fail, and the `awaiting-verification` label path when gates pass.
  - Replace the final `awaiting-verification` comment's human-verification text with a version that instructs the pipeline — not the reporter — to confirm: _"Verification will proceed automatically via the e2e workflow conclusion. No human comment is required on the green path."_
  - Remove the `verify` phrase list that prompts human confirmation (the `verify-comment-close.yml` file is superseded by Task 3's `e2e-verify-close.yml`).

### Task 3: Add `e2e-verify-close.yml` — `workflow_run`-driven verification handler

- **File:** `.github/workflows/e2e-verify-close.yml` (create)
- **Where:** New file alongside the other lifecycle workflows
- **What:** A workflow triggered on `workflow_run` completion that closes `awaiting-verification` issues automatically when a designated e2e workflow finishes with `conclusion == 'success'`.
- **Detail:**
  - Trigger: `workflow_run` with `types: [completed]`. The `workflows:` list is set to `["E2E Integration Tests"]` as a default value; product-repo owners must rename it to match their actual e2e workflow name by editing the file after seeding. A prominent `# CONFIGURE: replace "E2E Integration Tests" with your actual e2e workflow name` comment must appear directly above the `workflows:` key.
  - Job `verify-on-e2e-green`: runs only when `github.event.workflow_run.conclusion == 'success'`.
  - Reads the workflow run's `head_sha`, finds the most-recently-merged `impl:` PR whose `merge_commit_sha` matches (or whose `head.sha` matches), extracts the linked issue number from that PR title pattern `Issue #(\d+)`.
  - Checks the linked issue for the `awaiting-verification` label. If present: removes `awaiting-verification`, closes the issue, adds a comment `"Closed automatically: e2e workflow passed on commit <sha>."`.
  - Job `handle-e2e-red`: runs only when `github.event.workflow_run.conclusion != 'success'` and `!= 'skipped'` and `!= 'cancelled'`. Finds the same linked issue; if it carries `awaiting-verification`, adds label `e2e-failed`, posts a comment with the workflow run URL.
  - `permissions`: `issues: write`, `pull-requests: read`, `actions: read`.
  - Issue write operations (label changes, comments, state update) use `secrets.PUSH_TOKEN`. The workflow `on:` trigger condition itself requires no token — `workflow_run` events are triggered by GitHub Actions infrastructure, not by an authenticated API call.

### Task 4: Replace `verify-comment-close.yml` with a no-op notice

- **File:** `.github/workflows/verify-comment-close.yml` (modify)
- **Where:** Replace the entire job body
- **What:** Keep the file but change the job to emit a notice that human-comment verification is no longer the primary path and exit without closing.
- **Detail:** Replace the `close-on-verify` job's `steps` with a single `actions/github-script` step that calls `core.notice("awaiting-verification is now resolved by e2e workflow conclusion (e2e-verify-close.yml). Human comment ignored on the green path.")` and returns without modifying the issue. This prevents accidental human-triggered closes while keeping the file present so existing product repos that reference it do not break on update.

### Task 5: Add integration-test policy to `copilot-instructions.md`

- **File:** `.github/copilot-instructions.md` (modify)
- **Where:** After the `## Security Considerations` section, add a new `## Test Policy` section
- **What:** Document the rule that bug-fix PRs touching network/critical paths must include an integration test (not only predicate unit tests), so Goose and Copilot generate appropriate test types upfront.
- **Detail:** Add the following section verbatim (without placeholder tokens):

  ```
  ## Test Policy

  - All code changes need tests (target 80%+ coverage).
  - **Bug fixes on network or critical paths** (e.g., connection handling, protocol state machines, peer discovery, NAT traversal, relay routing, RPC, distributed state) must include at least one integration test that exercises the actual behavior path reported in the bug — predicate unit tests alone do not satisfy the gate.
  - Integration test files must be named with the suffix `_integration_test` (Go), `_integration_test.py` (Python), or `.integration.test` (JS/TS) so the impl-merged-close gate can distinguish them from unit tests. A _predicate unit test_ verifies an isolated decision function (e.g., "does `shouldRelayPeer()` return true when handshake is stale?") — it cannot reproduce network-level failure modes. An _integration test_ exercises the actual runtime path against real or simulated infrastructure (e.g., a two-node mesh that verifies the relay actually engages without a connectivity blackout).
  - Goose: when implementing a spec for a `type: bug` issue whose body describes a network or distributed-system behavior, always add an integration test in addition to any unit tests.
  ```

### Task 6: Add unit tests for `impl-merged-close-handler.js`

- **File:** `scripts/workflows/impl-merged-close-handler.test.js` (create)
- **Where:** New file alongside the handler
- **What:** Port the wgmesh unit-test suite for the handler, replacing Go-specific regex patterns with the multi-language patterns introduced in Task 2.
- **Detail:** Use Node.js built-in `node:test` runner (no external dependencies). Cover: `extractRepoTokens` (empty body, body with repro section, body without repro section, stop-word filtering), `isBug` (label shapes: string array, object array, mixed), `detectNewTestFuncs` (added `.go` test file, added `.py` test file, added `.test.js` file, renamed file, removed file, patch without new tests, empty PR). Mock `github.rest.repos.getContent` and `github.paginate` inline. All tests must pass with `node --test scripts/workflows/impl-merged-close-handler.test.js`.

### Task 7: Create `scripts/sync-gate-from-wgmesh.sh`

- **File:** `scripts/sync-gate-from-wgmesh.sh` (create)
- **Where:** New file
- **What:** A one-shot shell script that diffs gate-related workflow files between this template repo and a target seeded product repo to surface drift.
- **Detail:** The script accepts a single argument: the `owner/repo` of the seeded product (e.g. `atvirokodosprendimai/wgmesh`). It uses `gh api` to download the current content of `.github/workflows/impl-merged-close.yml`, `.github/workflows/e2e-verify-close.yml`, and `scripts/workflows/impl-merged-close-handler.js` from the remote product repo, then `diff` each against the local template copy. Output is a human-readable summary of lines that differ. Exit 0 when no diff, exit 1 when any diff detected. Script must be `chmod +x` and include a usage comment at the top.

## Affected Files

.github/workflows/impl-merged-close.yml                      (modify)
.github/workflows/e2e-verify-close.yml                       (new)
.github/workflows/verify-comment-close.yml                   (modify)
.github/copilot-instructions.md                              (modify)
scripts/workflows/impl-merged-close-handler.js               (new)
scripts/workflows/impl-merged-close-handler.test.js          (new)
scripts/sync-gate-from-wgmesh.sh                             (new)  (no-test)

## Test Strategy

- `bash .github/scripts/validate-spec.sh specs/issue-739-spec.md` passes with zero FAILs.
- `node --test scripts/workflows/impl-merged-close-handler.test.js` passes after implementation.
- After implementation: open a test `impl: Issue #739` PR against a scratch branch that adds a `_test.go`-like file and confirm the `close-issue` job invokes the handler and routes to `awaiting-verification` (not immediate close).
- After implementation: trigger `e2e-verify-close.yml` via `workflow_dispatch` (or simulate a `workflow_run` event with `act`) and confirm the linked `awaiting-verification` issue is closed and the comment contains the e2e SHA.
- After implementation: run `scripts/sync-gate-from-wgmesh.sh atvirokodosprendimai/wgmesh` and confirm it exits 0 when template and product are in sync, 1 when a deliberate diff is introduced.
- `verify-comment-close.yml` manual trigger: post `verified` comment on an `awaiting-verification` issue and confirm the issue is NOT closed (notice emitted, no state change).

## Estimated Complexity
medium
