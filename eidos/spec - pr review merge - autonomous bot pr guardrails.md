---
tldr: Autonomous review-and-merge loop for bot-authored PRs with layered guardrails and human escalation on any failure
category: core
---

# PR Review and Merge

## Target

Enable bot-authored PRs to land on `main` without human involvement while preserving a human-reviewable audit trail and a clear escalation path when the bot cannot safely proceed.

The subsystem absorbs all coordination overhead — waiting for Copilot review, negotiating fix cycles with the authoring agent, enforcing safety constraints, and merging — so the rest of the pipeline never stalls on a human gate.

## Behaviour

- Only PRs from an explicit author allowlist are eligible for autonomous merge; any unknown author immediately escalates. {>> `APPROVED_AUTHORS` env var, comma-separated, checked as the first and cheapest guardrail}
- The workflow triggers on PR open/reopen and runs the script from `main`, not from the PR branch, so the review logic is never tampered with by the PR under review. {>> `actions/checkout@v4` with `ref: main`}
- The script polls for a Copilot review across configurable windows before proceeding; if no review arrives within the total polling budget the PR escalates rather than merging blind. {>> `POLL_INTERVAL * POLL_MAX_ATTEMPTS * REVIEW_WINDOWS` seconds total budget, default ~6 min}
- When a Copilot review contains unresolved threads, the authoring agent is re-assigned with the review feedback as custom instructions; the fix loop repeats up to `MAX_RETRY_COUNT` times before escalating. {>> re-assignment uses `/issues/{pr}/assignees` with `agent_assignment.custom_instructions`}
- A human commit on the PR branch resets the fix-loop retry counter, so a human intervention is never penalised by the bot's prior failures. {>> `check_manual_push` compares latest commit author against `APPROVED_AUTHORS`}
- Adding a `manual-only` label to any PR causes the script to exit immediately without taking any automated action.
- Five layered guardrails run in cheapest-first order before merge; the first failure short-circuits the remainder and escalates: author allowlist, protected paths, PR size, security keyword scan of the diff, CI status. {>> order is deliberate — author and path checks require only PR metadata; diff scan and CI check are more expensive}
- PRs touching protected path prefixes are blocked regardless of author or size. {>> `PROTECTED_PATHS` env var; by default covers `.github/` and `company/scripts/`}
- PRs exceeding `PR_MAX_LINES` changed lines (additions + deletions) are blocked; large PRs need human judgement. {>> default 500 lines}
- Any added diff line containing a configured security keyword causes immediate escalation; the scan covers only additions (`grep '^+'`), not context or deletions. {>> `SECURITY_KEYWORDS` default: `secret,token,password,api_key,private_key,credentials,authorization`}
- For `spec:` titled PRs, the script waits for a `spec-validation` signal before merging: it escalates on `spec-needs-fix`, proceeds only on `approved-for-build`, and escalates on timeout if neither label appears. {>> polls up to 6 × 30 s = 3 min for the validation label}
- Every escalation adds the `needs-human` label and posts a sanitised comment explaining the reason; all published content passes through `sanitise.sh` before reaching the API. {>> escalation reason is sanitised; if sanitisation itself fails the reason is replaced with `[content redacted — sanitisation failure]`}
- All public-facing strings — PR comments and agent re-assignment instructions — are passed through `sanitise.sh`, which scans for secrets and PII and refuses to output if a secret pattern is detected.
- Merge is squash-only with branch deletion; if the merge command fails, one retry is attempted after a brief delay before escalating. {>> `gh pr merge --squash --admin --delete-branch`; idempotency check reads PR state before attempting}
- A circuit breaker halts the script with exit 1 after five cumulative errors; every error increments a shared counter that is checked after each fallible operation. {>> `ERRORS` counter + `check_circuit_breaker` called after every `ERRORS` increment}
- Every significant decision (start, review detected, retry, guardrails passed, escalated, merged) is appended to a JSONL audit log with timestamp, run ID, PR number, and repository. {>> `company/audit-log.jsonl`; JSON constructed exclusively with `jq -nc --arg` to avoid injection}
- Required environment variables (`PR_NUMBER`, `TARGET_REPO`, `GH_TOKEN`) are validated at script start with `bash` parameter expansion fail-fast; the script never proceeds with missing config.
- The script exits 0 on both successful merge and successful escalation; exit 1 is reserved for fatal infrastructure failure (circuit breaker triggered or script bug).

## Design

**Why PUSH_TOKEN, not GITHUB_TOKEN.**
GitHub deliberately prevents actions taken with `GITHUB_TOKEN` from triggering further workflow events — this is a security feature to break infinite loops. A separate merge workflow listening on `pull_request_review` would therefore never fire when the review comes from a GitHub App (Copilot). `PUSH_TOKEN` is a PAT scoped to the pipeline's own identity; it does trigger events, but more importantly it carries `admin` permission allowing `--admin` merge bypass of branch protection. The tradeoff (PAT rotation, narrower scope of automation) is accepted because the alternative is silently broken automation.

**Guardrails as intent enforcement, not path restrictions.**
The pipeline is goal-oriented: land bot work on `main` without human gates. Guardrails exist to protect that goal from edge cases — unknown authors, infrastructure self-modification, runaway diffs, credential leakage, and broken CI. Each guardrail is independently escapable by a human (via `manual-only` label or direct override) but cannot be bypassed by the bot. This keeps the happy path fully autonomous while keeping the escape hatch open.

**Script runs from `main`, not the PR branch.**
The review-merge logic is checked out from `main` at workflow start. A bot PR cannot modify its own review criteria; any attempt to weaken guardrails via a PR would require a human to merge that change first. This property holds even when `PROTECTED_PATHS` is empty.

**Polling over event-driven for Copilot reviews.**
GitHub Apps post reviews using `GITHUB_TOKEN`, which does not emit `pull_request_review` events. A workflow triggered by that event would never run. Polling is the only reliable mechanism. The configurable windows + attempts model gives the review service time to respond while bounding total wait time.

**Sanitise at output, not at input.**
`sanitise.sh` runs immediately before any string reaches a GitHub API call. This is a last-line defence: even if review comments or agent feedback contain secrets, they are caught before they are published to PR comments or passed as LLM instructions. Sanitisation failure is treated as a blocking error; the content is replaced with a safe stub rather than silently published.

**Andon over silent failure.**
Every `gh` call is wrapped in an explicit `if !` guard. No bare `|| true`. Every failure path increments the error counter, emits a GitHub Actions annotation (`::warning::` or `::error::`), and writes an audit entry. The circuit breaker at five errors converts a degraded-mode run into a hard stop before state becomes incoherent.

**jq for all JSON construction.**
No JSON is built by string interpolation. All payloads — audit log entries, PR comments, agent instructions — use `jq -nc --arg`. This eliminates a class of injection bugs where untrusted content (review body, file paths) could escape a JSON string boundary.

**Fix loop retry with manual-push reset.**
The retry counter tracks how many times the bot has been given a chance to fix its own PR. A human commit represents a qualitatively different kind of intervention and should not consume a bot retry slot. Detecting it resets the counter so the human's fix gets a fresh review cycle.

## Interactions

- [[spec - pipeline state machine - label driven issue lifecycle]] — the `needs-human` and `manual-only` labels used by this subsystem are part of the shared label vocabulary managed by the state machine
- [[spec - self healing - deterministic pipeline recovery]] — when this subsystem escalates rather than merges, recovery is expected to be handled by the self-healing loop
- [[spec - security quality - constitution and enforcement]] — the ARCH-4, SEC-2, SEC-7, QUAL-1, QUAL-5, QUAL-6, QUAL-7, ARCH-5 rules encoded here are derived from the constitution

## Mapping

- [[.github/workflows/bot-pr-review-merge.yml]]
- [[company/scripts/pr-review-merge.sh]]
- [[company/scripts/sanitise.sh]]
- [[docs/patterns/pr-review-merge.md]]
- [[docs/patterns/workflow-self-merge.md]]
