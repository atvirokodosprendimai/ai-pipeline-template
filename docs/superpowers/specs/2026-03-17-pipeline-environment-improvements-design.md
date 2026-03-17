# Pipeline Environment Improvements

## Context

The ai-pipeline-template repo is the control plane for autonomous development across all observed repos. Three systemic issues were identified by reviewing wgmesh PR #462 (a Copilot-authored spec):

1. `copilot-instructions.md` and `.goosehints` contain unfilled placeholders after `init.sh` runs — agents get no real project context from these files
2. No automated validation exists between "Copilot opens spec PR" and "Goose implements" — bad specs reach the implementation agent unchecked
3. The spec template lacks constraints that prevent common spec anti-patterns (line number references, mismatched test files, silent error swallowing)

## Design Principles

- **Human is a fallback, not a gate** — the pipeline self-corrects. Spec validation auto-approves when structural checks pass. Human intervenes only when validation fails. This is an intentional design decision: the observation loop, Copilot, Goose, and validation form a closed autonomous loop.
- Structural checks only (deterministic, zero cost) — LLM semantic pass deferred to v2
- Seed + live context — `init.sh` provides a baseline, workflows inject fresh codebase context at runtime
- Changes live in this repo, propagate to all adopters

## Initiative 1: Fix init/deploy + live context injection

### init.sh changes

Add two new prompts after the existing project prompts (after `prompt PROJECT_DESC`):

```bash
prompt PROJECT_STRUCTURE "Brief project structure (e.g. 'monorepo with pkg/ for libraries and cmd/ for CLI')"
prompt ARCHITECTURE_NOTES "Key architectural patterns (e.g. 'event-driven, repository pattern, CQRS')" ""
```

Note: `ARCHITECTURE_NOTES` defaults to empty string (not "none") to avoid literal "none" appearing in templates. When empty, the Architecture section simply renders blank.

Add corresponding replacement pairs to the `PAIRS` block (after the `__SETUP_WITH__` pair):

```bash
PAIRS="${PAIRS}__PROJECT_STRUCTURE__|$(esc "$PROJECT_STRUCTURE")
"
PAIRS="${PAIRS}__ARCHITECTURE_NOTES__|$(esc "$ARCHITECTURE_NOTES")
"
```

### copilot-instructions.md template updates

Replace TODO placeholders with real template sections that get filled by `init.sh`:

```markdown
## Project Structure

__PROJECT_STRUCTURE__

## Build & Test

- Build: `__BUILD_CMD__`
- Test: `__TEST_CMD__`
- Lint: `__LINT_CMD__`
- Format: `__FORMAT_CMD__`

## Architecture

__ARCHITECTURE_NOTES__
```

### .goosehints template updates

Same pattern — replace TODOs with filled template:

```
This is __PROJECT_NAME__ — __PROJECT_DESCRIPTION__.

## Structure
__PROJECT_STRUCTURE__

## Commands
- Build: __BUILD_CMD__
- Test: __TEST_CMD__
- Lint: __LINT_CMD__
- Format: __FORMAT_CMD__

## Architecture
__ARCHITECTURE_NOTES__

## Rules
- Do NOT modify files outside the scope of the specification
- Run build, test, and lint before considering work complete
- Keep changes minimal and focused
```

### Live context injection — copilot-triage.yml

Before assigning Copilot, fetch `CLAUDE.md` from the repo being triaged and inject it into the agent instructions.

The workflow already runs in the context of the target repo (it's deployed there via the template). So `CLAUDE.md` is accessible directly. Add to `specInstructions`:

```javascript
// Prepend live project context
const specInstructions = [
  `## Live Project Context`,
  ``,
  `Before writing the spec, read the CLAUDE.md file in the repository root.`,
  `It contains the current architecture, build commands, and conventions.`,
  `Use it as ground truth for what exists. Do NOT create specs for features`,
  `already described there.`,
  ``,
  // ... existing spec instructions
];
```

This is a lightweight approach — we tell Copilot to read `CLAUDE.md` rather than fetching and inlining it (which would bloat the assignment payload). Copilot already explores the codebase; this ensures `CLAUDE.md` is the first file it reads.

### Live context injection — goose-build.yml

In the "Build Goose instructions" step, after writing the task header and before appending the spec, inject the repo's `CLAUDE.md`:

```bash
# Inject live project context if CLAUDE.md exists
if [ -f "CLAUDE.md" ]; then
  echo "" >> /tmp/goose-task.md
  echo "## Project Context (from CLAUDE.md)" >> /tmp/goose-task.md
  echo "" >> /tmp/goose-task.md
  cat CLAUDE.md >> /tmp/goose-task.md
  echo "" >> /tmp/goose-task.md
fi
```

Also update the Goose Implementation Checklist to reference "Implementation Tasks" instead of "Proposed Approach":

```
3. Implement the changes described in "Implementation Tasks"
```

## Initiative 2: Spec validation + auto-approve

### Pipeline behavior change

This initiative intentionally removes the human gate from the spec→build flow. The new pipeline is:

```
Issue → Copilot writes spec → spec PR → automated validation → auto-approve → Goose implements
```

Human is notified at every step but does not block. If validation fails, the PR gets `spec-needs-fix` and Copilot (or a human) must push a fix before auto-approval proceeds.

### Enabling the Goose PR trigger

The `goose-build.yml` file currently has its `pull_request: [labeled]` trigger commented out. This must be uncommented for auto-approval to trigger Goose:

```yaml
on:
  pull_request:
    types: [labeled]
  workflow_dispatch:
    # ... existing inputs
```

### New workflow: .github/workflows/spec-validation.yml

**Trigger:** `pull_request` (opened, synchronize) where at least one changed file matches `specs/issue-*-spec.md`.

**Checks (all structural, deterministic, zero API cost):**

| # | Check | Pattern | Severity |
|---|-------|---------|----------|
| 1 | Required sections present | grep for `## Classification`, `## Problem Analysis`, `## Implementation Tasks`, `## Affected Files`, `## Test Strategy`, `## Estimated Complexity`, `## Deliverables` | error |
| 2 | No line number references | grep -iE `(after line\|at line\|on line\|lines? [0-9])` — ignoring HTML comments and code blocks | error |
| 3 | Test file naming matches source | parse Affected Files section; for each source file verify corresponding test file exists in list OR the annotation `(no-test)` appears next to the file entry | warning |
| 4 | No placeholder tokens | grep `__[A-Z_]+__` — ignoring HTML comments | error |
| 5 | Affected Files non-empty | section exists and has at least one file listed | error |
| 6 | Valid classification | first non-empty, non-comment line after `## Classification` heading is one of: fix, feature, refactor, wont-do, needs-info | error |

**Output format for validate-spec.sh:**

One line per check, pipe-delimited:
```
CHECK_NAME|PASS|
CHECK_NAME|FAIL|detail message explaining what's wrong
CHECK_NAME|WARN|detail message (non-blocking)
```

Exit code: 0 if zero FAIL lines, 1 if any FAIL lines.

**On all checks pass (zero errors):**
- Remove `spec-needs-fix` label if present
- Add `approved-for-build` label to the spec PR
- Post a brief approval comment: "Spec validation passed. Auto-approved for build."

**On any error:**
- Remove `approved-for-build` label if present (handles re-push regression)
- Post PR review comment listing each failure with the check name, the offending text, and a fix suggestion
- Add `spec-needs-fix` label
- Do NOT add `approved-for-build`

**On re-push (synchronize):**
- Re-run all checks from scratch
- Label management handles both directions (pass→fail and fail→pass)

### New labels in .github/labels.yml

Add:
```yaml
- name: approved-for-build
  color: "0E8A16"
  description: "Spec passed validation, ready for Goose implementation"

- name: spec-needs-fix
  color: "E11D48"
  description: "Spec validation found structural issues"
```

### Workflow structure

```yaml
name: Spec Validation

on:
  pull_request:
    types: [opened, synchronize]
    paths:
      - 'specs/issue-*-spec.md'

permissions:
  contents: read
  pull-requests: write

jobs:
  validate:
    if: "!contains(github.repository, 'ai-pipeline-template')"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # need base SHA for diff

      - name: Find spec file
        id: find
        uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          script: |
            const files = await github.paginate(github.rest.pulls.listFiles, {
              owner: context.repo.owner,
              repo: context.repo.repo,
              pull_number: context.issue.number,
              per_page: 100,
            });
            const spec = files.find(f => /^specs\/issue-\d+-spec\.md$/.test(f.filename));
            if (!spec) {
              core.setFailed('No spec file found in PR');
              return;
            }
            core.setOutput('spec_file', spec.filename);

      - name: Run structural checks
        id: checks
        run: |
          bash .github/scripts/validate-spec.sh "${{ steps.find.outputs.spec_file }}" | tee /tmp/validation-results.txt
          # Script exits 1 on failure, which fails this step

      - name: Auto-approve or flag
        if: always()
        uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          script: |
            const fs = require('fs');
            const results = fs.readFileSync('/tmp/validation-results.txt', 'utf8').trim().split('\n');

            const failures = results.filter(r => r.includes('|FAIL|'));
            const warnings = results.filter(r => r.includes('|WARN|'));
            const passed = failures.length === 0;

            const prNumber = context.issue.number;

            if (passed) {
              // Remove spec-needs-fix if present
              try {
                await github.rest.issues.removeLabel({
                  owner: context.repo.owner, repo: context.repo.repo,
                  issue_number: prNumber, name: 'spec-needs-fix'
                });
              } catch (e) { /* label not present */ }

              // Add approved-for-build
              await github.rest.issues.addLabels({
                owner: context.repo.owner, repo: context.repo.repo,
                issue_number: prNumber, labels: ['approved-for-build']
              });

              let body = 'Spec validation passed. Auto-approved for build.';
              if (warnings.length > 0) {
                body += '\n\n**Warnings (non-blocking):**\n' +
                  warnings.map(w => '- ' + w.split('|')[2]).join('\n');
              }
              await github.rest.issues.createComment({
                owner: context.repo.owner, repo: context.repo.repo,
                issue_number: prNumber, body
              });
            } else {
              // Remove approved-for-build if present (re-push regression)
              try {
                await github.rest.issues.removeLabel({
                  owner: context.repo.owner, repo: context.repo.repo,
                  issue_number: prNumber, name: 'approved-for-build'
                });
              } catch (e) { /* label not present */ }

              // Add spec-needs-fix
              await github.rest.issues.addLabels({
                owner: context.repo.owner, repo: context.repo.repo,
                issue_number: prNumber, labels: ['spec-needs-fix']
              });

              const body = '**Spec validation failed.**\n\n' +
                failures.map(f => {
                  const [name, , detail] = f.split('|');
                  return `- **${name}**: ${detail}`;
                }).join('\n') +
                (warnings.length > 0
                  ? '\n\n**Warnings:**\n' + warnings.map(w => '- ' + w.split('|')[2]).join('\n')
                  : '');

              await github.rest.issues.createComment({
                owner: context.repo.owner, repo: context.repo.repo,
                issue_number: prNumber, body
              });
            }
```

### Validation script: .github/scripts/validate-spec.sh

A standalone bash script that:
- Takes a spec file path as argument
- Runs each check
- Outputs one line per check: `CHECK_NAME|PASS|` or `CHECK_NAME|FAIL|detail` or `CHECK_NAME|WARN|detail`
- Exits 0 if all pass, exits 1 if any FAIL

This keeps the logic testable outside of GitHub Actions.

## Initiative 3: Harden spec template

### Move spec template to copilot-instructions.md

The spec template is currently embedded as a JS string array in `copilot-triage.yml`. This is:
- Hard to read and maintain
- Not available to Copilot when it reads project files
- Duplicated between `copilot-instructions.md` and `copilot-triage.yml`

Move the canonical spec template (with all rules) into `copilot-instructions.md` under the "When Triaging Issues" section. Then simplify `copilot-triage.yml` to reference it:

```javascript
const specInstructions = [
  `## Live Project Context`,
  ``,
  `Before writing the spec, read the CLAUDE.md file in the repository root.`,
  `It contains the current architecture, build commands, and conventions.`,
  `Use it as ground truth for what exists. Do NOT create specs for features`,
  `already described there.`,
  ``,
  `## Spec Instructions`,
  ``,
  `Read the spec template and rules in .github/copilot-instructions.md under`,
  `"When Triaging Issues (Spec-Only Mode)". Follow it exactly.`,
  ``,
  `Create the spec file at specs/issue-${issueNumber}-spec.md`,
  `Open a PR titled: spec: Issue #${issueNumber} - ${safeTitle}`,
  `Include "Issue #${issueNumber}" in the title for pipeline traceability.`,
  `Target the main branch.`,
  `The PR should contain ONLY the spec file - no code changes.`,
].join('\n');
```

### Updated spec template in copilot-instructions.md

```markdown
## When Triaging Issues (Spec-Only Mode)

When asked to triage an issue and write a specification:

1. **Read CLAUDE.md first** — understand what already exists
2. **Explore the relevant code** — read the actual functions, don't guess
3. **Create the spec file** at `specs/issue-{NUMBER}-spec.md`
4. **Open a PR** titled: `spec: Issue #{NUMBER} - {brief description}`
5. Target `main`. Include ONLY the spec file — no code changes.

### Spec Template

Use this exact structure:

    # Specification: Issue #{NUMBER}

    ## Classification
    <!-- One of: fix, feature, refactor, wont-do, needs-info -->

    ## Deliverables
    <!-- One of: code, documentation, both -->

    ## Problem Analysis
    <!-- What is wrong or missing. Reference actual code by function/type name.
         NEVER reference line numbers — they drift between spec and implementation. -->

    ## Implementation Tasks

    ### Task 1: <short name>
    - **File:** `path/to/file.ext` (create | modify)
    - **Where:** After `FunctionName()` | At end of file | New file
    - **What:** Add function `FuncName(args) ReturnType` that does X
    - **Detail:** 2-4 sentences. No ambiguity. An AI agent must implement from this alone.

    ### Task 2: <short name>
    - **File:** `path/to/file_test.ext` (create | modify)
    - **What:** Add `TestFuncName_Scenario` that asserts Y
    - **Detail:** Table-driven test. Mock Z. Cover normal, edge, and error cases.

    <!-- Repeat for every file change. No placeholders like "modify as needed". -->

    ## Affected Files
    <!-- Exhaustive list matching Implementation Tasks above.
         Append (no-test) if a source file intentionally has no test changes. -->
    path/to/file.ext        (new | modify)
    path/to/file_test.ext   (new | modify)

    ## Test Strategy
    <!-- How to verify. Must be runnable commands, not prose. -->
    - `<build command>` passes
    - `<test command> ./path/to/...` passes including new tests
    - Specific behavioral assertions

    ## Estimated Complexity
    <!-- One of: low (1-2 files, <100 lines), medium (3-5 files), high (>5 files) -->

### Spec Rules (CRITICAL — violations will be auto-rejected)

1. **No line numbers** — use function names, type names, or string patterns to locate code
2. **Test files match source** — `pkg/foo/bar.go` → `pkg/foo/bar_test.go`, not an unrelated file
3. **Explicit error handling** — if ignoring errors with `_`, explain why in a comment
4. **Self-contained** — an agent reading only this spec can implement it without guessing
5. **No duplicate features** — verify against CLAUDE.md before proposing
6. **No placeholder tokens** — never use `__PLACEHOLDER__` patterns in spec content
```

## Affected Files

```
init.sh                                     (modify)
.github/copilot-instructions.md             (modify)
.github/workflows/copilot-triage.yml        (modify)
.github/workflows/goose-build.yml           (modify — CLAUDE.md injection + uncomment PR trigger + update "Proposed Approach" → "Implementation Tasks")
.github/workflows/spec-validation.yml       (new)
.github/scripts/validate-spec.sh            (new)
.github/labels.yml                          (modify — add approved-for-build and spec-needs-fix)
.goosehints                                 (modify)
```

## Test Strategy

- Run `bash .github/scripts/validate-spec.sh` against a test spec with known violations (line numbers, missing sections, placeholder tokens) and verify the script catches them
- Run against a clean spec to verify it passes
- Verify `init.sh` still runs cleanly with the new prompts (manual dry run)
- Verify workflow YAML syntax: `actionlint` if available
- Verify `copilot-triage.yml` JS syntax is valid

## Estimated Complexity

medium (8 files, mix of new and modify)
