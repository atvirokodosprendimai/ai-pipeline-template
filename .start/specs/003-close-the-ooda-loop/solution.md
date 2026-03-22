---
title: "Close the OODA Loop"
status: complete
version: "1.0"
---

# Solution Design Document

## The Complete Loop After This Spec

```
observe (observation-loop) → issues → triage (copilot-triage.yml)
  → spec PR (copilot-swe-agent) → spec-validation auto-approves
  → bot-pr-review-merge.yml merges spec PR
  → spec-merged-build.yml detects merge, assigns copilot-swe-agent to implement
  → impl PR (copilot-swe-agent) → bot-pr-review-merge.yml merges impl PR
  → impl-merged-close.yml closes issue
  → back to observe
```

Zero human gates. Every transition is a workflow.

## Changes

### 1. Remove template repo skip from spec-validation.yml

**File:** `.github/workflows/spec-validation.yml`
**Change:** Remove line 19: `if: "!contains(github.repository, 'ai-pipeline-template')"`

This was a bootstrap guard — the template repo didn't have spec-validation infrastructure initially. It does now. Remove the guard so the pipeline can improve itself.

### 2. Auto-merge spec PRs via universal trigger

**No new workflow needed.** The universal `bot-pr-review-merge.yml` (from Feature 4) triggers on `pull_request: [opened]` for bot authors. Spec PRs created by copilot-swe-agent will be caught by this workflow. The spec-validation workflow adds `approved-for-build` and pr-review-merge.sh handles the merge.

**Sequencing concern:** spec-validation and bot-pr-review-merge both trigger on `pull_request: [opened]`. pr-review-merge.sh polls for Copilot review (3-6 min). spec-validation runs fast (~30s). By the time pr-review-merge.sh is ready to merge, spec-validation has already labeled it. If spec-validation fails, pr-review-merge.sh will see the `spec-needs-fix` label — we need pr-review-merge.sh to check for this label and escalate instead of merging.

**Script change:** Add `spec-needs-fix` as an escalation label in pr-review-merge.sh. If present after guardrails pass, escalate instead of merge. This prevents merging a spec that failed validation.

### 3. Build trigger on spec merge

**New file:** `.github/workflows/spec-merged-build.yml`

```yaml
name: Spec Merged — Trigger Build

on:
  pull_request:
    types: [closed]

jobs:
  trigger-build:
    if: >-
      github.event.pull_request.merged == true &&
      contains(github.event.pull_request.title, 'spec:')
    runs-on: ubuntu-latest
    steps:
      - name: Assign build agent to implement spec
        uses: actions/github-script@v8
        with:
          github-token: ${{ secrets.PUSH_TOKEN }}
          script: |
            const pr = context.payload.pull_request;
            const issueMatch = pr.title.match(/Issue #(\d+)/);
            if (!issueMatch) {
              core.warning('No issue number in spec PR title: ' + pr.title);
              return;
            }
            const issueNumber = parseInt(issueMatch[1], 10);
            const specFile = `specs/issue-${issueNumber}-spec.md`;

            await github.request('POST /repos/{owner}/{repo}/issues/{issue_number}/assignees', {
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: issueNumber,
              assignees: ['copilot-swe-agent[bot]'],
              agent_assignment: {
                custom_instructions: [
                  `The spec for issue #${issueNumber} has been approved and merged.`,
                  `Read the spec at ${specFile} and implement it.`,
                  `Open a PR with the implementation. Include "Issue #${issueNumber}" in the PR title.`,
                  `Write tests. Follow the project conventions in CLAUDE.md and .goosehints.`,
                ].join('\n'),
              },
              headers: { 'X-GitHub-Api-Version': '2022-11-28' },
            });

            await github.rest.issues.addLabels({
              owner: context.repo.owner, repo: context.repo.repo,
              issue_number: issueNumber, labels: ['building']
            });

            await github.rest.issues.createComment({
              owner: context.repo.owner, repo: context.repo.repo,
              issue_number: issueNumber,
              body: `Spec merged (PR #${pr.number}). Build agent assigned to implement.`
            });
```

**Permissions:** `issues: write`, `contents: read`, `pull-requests: read`

### 4. Universal bot PR review-merge

**New file:** `.github/workflows/bot-pr-review-merge.yml`

Same as spec 003's design — triggers on `pull_request: [opened]` for approved bot authors, calls `bash company/scripts/pr-review-merge.sh`.

**Also:** Remove inline pr-review-merge.sh calls from pipeline-health.yml and observation-loop.yml (same as spec 003).

### 5. Issue closure on impl merge

**New file:** `.github/workflows/impl-merged-close.yml`

```yaml
name: Implementation Merged — Close Issue

on:
  pull_request:
    types: [closed]

jobs:
  close-issue:
    if: >-
      github.event.pull_request.merged == true &&
      !contains(github.event.pull_request.title, 'spec:') &&
      !contains(github.event.pull_request.title, 'heal:') &&
      !contains(github.event.pull_request.title, 'loop:')
    runs-on: ubuntu-latest
    steps:
      - name: Close linked issue
        uses: actions/github-script@v8
        with:
          github-token: ${{ secrets.PUSH_TOKEN }}
          script: |
            const pr = context.payload.pull_request;
            const issueMatch = pr.title.match(/Issue #(\d+)/);
            if (!issueMatch) return; // No linked issue — skip silently

            const issueNumber = parseInt(issueMatch[1], 10);

            await github.rest.issues.update({
              owner: context.repo.owner, repo: context.repo.repo,
              issue_number: issueNumber, state: 'closed'
            });

            await github.rest.issues.createComment({
              owner: context.repo.owner, repo: context.repo.repo,
              issue_number: issueNumber,
              body: `Resolved by PR #${pr.number}. Implementation merged to main.`
            });
```

**Permissions:** `issues: write`, `pull-requests: read`

**Filter:** Excludes `spec:`, `heal:`, and `loop:` prefixed PRs — those are pipeline maintenance, not issue implementations.

### 6. Script change: spec-needs-fix escalation

**File:** `company/scripts/pr-review-merge.sh`
**Change:** After guardrails pass but before merge, check if PR has `spec-needs-fix` label. If yes, escalate with reason "spec validation failed."

## Architecture Decisions

- [x] **ADR-1: Reuse pr-review-merge.sh for spec PRs** — no separate spec merge workflow. The universal trigger + existing script handles everything.
- [x] **ADR-2: spec merge triggers build via pull_request:closed** — detects merged spec PRs and assigns the build agent to the original issue.
- [x] **ADR-3: Issue closure via pull_request:closed on impl PRs** — simple, event-driven, no polling.
- [x] **ADR-4: spec-needs-fix label blocks merge** — prevents merging specs that failed validation, even if Copilot review was clean.

## Constitution Compliance

All new workflows follow SEC-1 (secrets via env), SEC-3 (event context via env where applicable — github-script uses context object safely), SEC-4 (explicit permissions), ARCH-8 (PUSH_TOKEN). Andon compliance inherited from pr-review-merge.sh.
