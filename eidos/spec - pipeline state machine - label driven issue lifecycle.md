---
tldr: GitHub labels are the state machine — issues flow autonomously from creation through Copilot spec writing, human approval, and agent implementation to merge.
category: core
---

# Pipeline State Machine

## Target

Turn any GitHub issue into merged code without human intervention beyond a single approval gate. The pipeline converts an issue label into a series of label-driven state transitions, each triggering the right agent at the right moment. Human judgment is injected at exactly one point: approving the spec before implementation begins.

## Behaviour

- Any issue labeled `needs-triage`, `fn:dev`, or `bug` enters the pipeline. {>> These are the three entry labels checked in copilot-triage.yml. `fn:dev` flows from the observation loop; `bug` from manual reports; `needs-triage` from automated OODA assessment.}
- A guard condition prevents double-assignment: if `copilot-triaging` is already present, the triage workflow is a no-op. This makes label events idempotent.
- On entry, the trigger label is swapped for `copilot-triaging` and Copilot (`copilot-swe-agent[bot]`) is assigned via the GitHub agent assignment API with spec-writing instructions. The issue is never touched by a human agent at this stage.
- Copilot produces exactly one artifact: `specs/issue-{N}-spec.md`. The PR title must contain `spec: Issue #{N}` — this token is the traceability key linking spec PR to issue throughout the rest of the pipeline.
- Copilot PRs opened as drafts are automatically promoted to "ready for review" before any downstream automation runs. {>> copilot-undraft.yml fires on PR open, detected by `user.login == 'copilot-swe-agent[bot]'` and `draft == true`. This prevents the approval workflows from blocking on draft state.}
- Every spec PR undergoes structural validation before human review. Validation is deterministic (shell script, no LLM): it checks for required sections, forbidden patterns (line number references, unfilled `__PLACEHOLDER__` tokens), non-empty affected files, and a valid classification value. {>> validate-spec.sh emits `CHECK|PASS|`, `CHECK|FAIL|detail`, or `CHECK|WARN|detail` per check. Failures block the `approved-for-build` label; warnings are surfaced but non-blocking.}
- Validation outcome is communicated by label, not by CI status alone: a passing spec gets `approved-for-build`; a failing spec gets `spec-needs-fix`. Both states are visible on the Kanban dashboard.
- The human approval gate operates through GitHub's native PR review flow. Approving a spec PR with `spec:` in the title adds `approved-for-build` and notifies the originating issue. Requesting changes re-assigns Copilot with the reviewer's feedback verbatim and labels the PR `copilot-revising`. Closing without merging is silent rejection — no workflow fires.
- When a spec PR is merged, the build phase starts automatically: the originating issue receives `building` and Copilot is re-assigned with instructions to read the merged spec and produce an implementation PR including tests. {>> spec-merged-build.yml fires on `pull_request.closed` where `merged == true` and title contains `spec:`. Issue number is extracted from the PR title via regex.}
- Implementation PRs that merge to main and whose title contains `Issue #{N}` (but not `spec:`, `heal:`, or `loop:`) automatically close the originating issue with a resolution comment. {>> impl-merged-close.yml uses title-pattern exclusion to distinguish implementation PRs from pipeline-internal PRs.}
- The label set is infrastructure: `.github/labels.yml` is the single source of truth. Any push to that file on main re-syncs labels to the repo. Manual bootstrapping is possible via `workflow_dispatch`. {>> sync-labels.yml uses a simple line-by-line YAML parser — no external dependencies.}
- Issues labeled `wont-do`, `needs-info`, or `manual-only` are permanently exempt from self-healing retries. These are terminal states for issues that must not re-enter the autonomous flow.
- The pipeline is strictly forward-progressing. When conflicting labels are present (e.g., issue carries both `needs-triage` and `copilot-triaging`), the more advanced label wins for display purposes. Self-healing evaluates each label independently.
- All non-pipeline PRs (`heal:`, `loop:`, PRs with no `Issue #{N}` in the title) are excluded from issue-closing logic. Pipeline-internal automation does not accidentally close issues it does not own.

## Design

**Labels as state, not metadata.** Labels are not tags on an issue; they are the issue's position in a finite state machine. Adding or removing a label is a state transition that fires a workflow. This means the pipeline has no central orchestrator — each workflow is a pure function of label events.

**Idempotency via guard labels.** Before any workflow does work, it checks whether the work is already in progress by testing for the downstream label. This makes re-triggering (e.g., via self-healing label toggle) safe. The anti-duplication pattern is: `if downstream label already exists, skip`.

**PR title as the join key.** The pattern `Issue #{N}` in PR titles is the only mechanism linking a PR back to its originating issue across spec and build phases. This is deliberately simple — no database, no external state, just a regex on a string that humans write and bots parse.

**Spec-only first, code second.** The two-phase design (spec PR → impl PR) enforces that every piece of work is described before it is built. Copilot is instructed to produce no code in phase one. The spec is the contract that gates implementation.

**Deterministic validation, not LLM review.** Structural spec quality is checked by a shell script with explicit pass/fail/warn semantics. This means the validation result is reproducible, auditable, and cannot hallucinate. LLM judgment enters only through human review.

**Native GitHub primitives only.** The pipeline uses GitHub Issues, PRs, Labels, Actions, and the agent assignment API. No external orchestration platform, no webhooks to third-party services, no persistent server. The state lives in GitHub.

**Draft auto-promotion removes a friction point.** Copilot opens PRs as drafts by default. A dedicated workflow immediately converts them to ready-for-review. Without this, auto-approval and review request workflows would wait on draft state indefinitely.

## Interactions

- The observation loop feeds issues into the pipeline by applying `needs-triage` or `fn:dev` labels. This subsystem is the source of most pipeline work. [[spec - observation loop - autonomous OODA cycle for company operations]]
- Self-healing monitors stale pipeline states (issues stuck in `needs-triage`, `copilot-triaging`, or `approved-for-build` beyond thresholds) and re-triggers transitions by toggling labels. It is a corrective layer, not a parallel pipeline. [[spec - self healing - deterministic pipeline recovery]]
- The spec PR approval workflow (`approve-build.yml`) is the implementation side of the PR review guardrails contract. Human approval is the only shared boundary between autonomous operation and human judgment. [[spec - pr review merge - autonomous bot pr guardrails]]
- The Kanban dashboard (chimney `/pipeline`) consumes labels to render column state. The label-to-column mapping is: `needs-triage` → Created, `copilot-triaging`/`copilot-revising` → Triaging, `spec-ready` → Spec PR, `approved-for-build` → Approved, `goose-implementation` → Implementing, merged → Merged.
- `.github/copilot-instructions.md` carries the spec template and rules that Copilot reads before writing. Changes there affect all future spec outputs.
- `CLAUDE.md` in the repo root is injected as live project context into Copilot's triage instructions. It prevents Copilot from speccing features that already exist.

## Mapping

> - [[.github/workflows/copilot-triage.yml]]
> - [[.github/workflows/spec-validation.yml]]
> - [[.github/workflows/approve-build.yml]]
> - [[.github/workflows/spec-merged-build.yml]]
> - [[.github/workflows/impl-merged-close.yml]]
> - [[.github/workflows/copilot-undraft.yml]]
> - [[.github/workflows/sync-labels.yml]]
> - [[.github/labels.yml]]
> - [[.github/scripts/validate-spec.sh]]
> - [[docs/domain/pipeline-state-machine.md]]
