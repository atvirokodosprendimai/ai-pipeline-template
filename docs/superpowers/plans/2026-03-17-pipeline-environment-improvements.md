# Pipeline Environment Improvements — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the autonomous dev pipeline so agents get real project context, specs are validated automatically, and human approval is no longer a gate.

**Architecture:** Three coordinated changes to the template repo: (1) `init.sh` seeds richer project context into `copilot-instructions.md` and `.goosehints`, while workflows inject live `CLAUDE.md` at runtime; (2) a new `spec-validation.yml` workflow runs structural checks on spec PRs and auto-approves clean ones; (3) the spec template moves from inline JS to `copilot-instructions.md` with stricter rules.

**Tech Stack:** Bash, GitHub Actions YAML, GitHub Script (JS), standard Unix tools (grep, sed, awk)

**Spec:** `docs/superpowers/specs/2026-03-17-pipeline-environment-improvements-design.md`

---

## Chunk 1: Initiative 3 — Harden spec template

Initiative 3 first because it defines the spec template that Initiative 2's validator checks against.

### Task 1: Rewrite copilot-instructions.md with full spec template and rules

**Files:**
- Modify: `.github/copilot-instructions.md`

- [ ] **Step 1: Rewrite copilot-instructions.md**

Replace the entire file. The new version:
- Fills project structure and architecture with `__PLACEHOLDER__` tokens (init.sh fills them)
- Moves the full spec template from `copilot-triage.yml` into this file
- Adds the 6 critical spec rules
- Adds `## Implementation Tasks` structured format
- Adds `## Deliverables` section
- Adds `(no-test)` annotation convention in Affected Files

```markdown
# Copilot Instructions for __PROJECT_NAME__

## Project Overview

__PROJECT_NAME__ is a __LANGUAGE__-based project. __PROJECT_DESCRIPTION__

## Code Style

- **Language**: __LANGUAGE__ __LANGUAGE_VERSION__
- **Formatting**: `__FORMAT_CMD__`

## Project Structure

__PROJECT_STRUCTURE__

## Build & Test

```
Build:  __BUILD_CMD__
Test:   __TEST_CMD__
Lint:   __LINT_CMD__
Format: __FORMAT_CMD__
```

## Architecture

__ARCHITECTURE_NOTES__

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

## Security Considerations

- Never hardcode secrets, keys, or tokens
```

- [ ] **Step 2: Commit**

```bash
git add .github/copilot-instructions.md
git commit -m "feat: rewrite copilot-instructions.md with full spec template and rules"
```

### Task 2: Simplify copilot-triage.yml to reference copilot-instructions.md

**Files:**
- Modify: `.github/workflows/copilot-triage.yml`

- [ ] **Step 1: Replace inline spec instructions with reference + live context**

In `copilot-triage.yml`, replace ONLY the `const specInstructions = [...]` array with the simplified version below. Everything after it (the `agent_assignment` API call, comment posting, label swapping) stays unchanged:

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

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/copilot-triage.yml
git commit -m "refactor: simplify copilot-triage to reference copilot-instructions.md"
```

---

## Chunk 2: Initiative 2 — Spec validation + auto-approve

### Task 3: Add new labels to labels.yml

**Files:**
- Modify: `.github/labels.yml`

- [ ] **Step 1: Update approved-for-build description and add spec-needs-fix**

The `approved-for-build` label already exists but has the wrong description. Update it and add `spec-needs-fix`:

Change the existing `approved-for-build` entry:
```yaml
- name: approved-for-build
  color: "0E8A16"
  description: "Spec passed validation, ready for Goose implementation"
```

Add after it:
```yaml
- name: spec-needs-fix
  color: "E11D48"
  description: "Spec validation found structural issues"
```

- [ ] **Step 2: Commit**

```bash
git add .github/labels.yml
git commit -m "feat: update approved-for-build label, add spec-needs-fix"
```

### Task 4: Create validate-spec.sh

**Files:**
- Create: `.github/scripts/validate-spec.sh`

- [ ] **Step 1: Create the scripts directory and validation script**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Spec Validation — structural checks for AI-generated spec files.
# Output: one line per check — CHECK_NAME|PASS| or CHECK_NAME|FAIL|detail or CHECK_NAME|WARN|detail
# Exit: 0 if zero FAILs, 1 if any FAIL.

SPEC_FILE="${1:?Usage: validate-spec.sh <spec-file>}"

if [ ! -f "$SPEC_FILE" ]; then
  echo "SPEC_EXISTS|FAIL|File not found: $SPEC_FILE"
  exit 1
fi

CONTENT=$(cat "$SPEC_FILE")
ERRORS=0

# ── Helper: strip HTML comments and fenced code blocks ──
strip_comments_and_code() {
  sed '/<!--/,/-->/d' | sed '/^```/,/^```/d'
}

CLEAN=$(echo "$CONTENT" | strip_comments_and_code)

# ── Check 1: Required sections ──
REQUIRED_SECTIONS=(
  "## Classification"
  "## Deliverables"
  "## Problem Analysis"
  "## Implementation Tasks"
  "## Affected Files"
  "## Test Strategy"
  "## Estimated Complexity"
)

MISSING=""
for section in "${REQUIRED_SECTIONS[@]}"; do
  if ! echo "$CONTENT" | grep -qF "$section"; then
    MISSING="${MISSING}${section}, "
  fi
done

if [ -n "$MISSING" ]; then
  echo "REQUIRED_SECTIONS|FAIL|Missing: ${MISSING%, }"
  ERRORS=$((ERRORS + 1))
else
  echo "REQUIRED_SECTIONS|PASS|"
fi

# ── Check 2: No line number references ──
# Search cleaned content (no comments/code blocks) for line number patterns.
LINE_REFS=$(echo "$CLEAN" | grep -inE '(after line|at line|on line|lines? [0-9])' || true)

if [ -n "$LINE_REFS" ]; then
  # Grab first offending line for the detail message
  FIRST=$(echo "$LINE_REFS" | head -1 | sed 's/^[0-9]*://')
  echo "NO_LINE_NUMBERS|FAIL|Found line number reference: ${FIRST:0:120}"
  ERRORS=$((ERRORS + 1))
else
  echo "NO_LINE_NUMBERS|PASS|"
fi

# ── Check 3: Test file naming matches source ──
# Extract Affected Files section, check that source files have matching test files.
AF_SECTION=$(echo "$CONTENT" | sed -n '/^## Affected Files/,/^## /p' | sed '1d;$d')

if [ -n "$AF_SECTION" ]; then
  WARN_FILES=""
  while IFS= read -r line; do
    alt_test=""
    # Skip empty lines, comments, and lines with (no-test)
    [[ -z "$line" || "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" =~ "<!--" ]] && continue
    [[ "$line" =~ "(no-test)" ]] && continue

    # Extract file path (first non-whitespace token)
    filepath=$(echo "$line" | awk '{print $1}')

    # Skip if it's already a test file
    [[ "$filepath" =~ _test\. || "$filepath" =~ \.test\. || "$filepath" =~ __test__ || "$filepath" =~ /tests?/ ]] && continue
    # Skip non-code files
    [[ "$filepath" =~ \.(md|yml|yaml|json|toml|txt)$ ]] && continue

    # Derive expected test file name
    ext="${filepath##*.}"
    base="${filepath%.*}"
    case "$ext" in
      go)    expected_test="${base}_test.go" ;;
      py)    expected_test="${base}_test.py"
             alt_test="test_$(basename "$base").py" ;;
      ts|js) expected_test="${base}.test.${ext}" ;;
      *)     continue ;;  # skip unknown extensions
    esac

    # Check if test file exists in Affected Files
    if ! echo "$AF_SECTION" | grep -qF "$(basename "$expected_test")"; then
      # Check alt pattern for Python
      if [ -n "${alt_test:-}" ] && echo "$AF_SECTION" | grep -qF "$(basename "$alt_test")"; then
        continue
      fi
      WARN_FILES="${WARN_FILES}${filepath}, "
    fi
  done <<< "$AF_SECTION"

  if [ -n "$WARN_FILES" ]; then
    echo "TEST_FILE_MATCH|WARN|Source files without matching test: ${WARN_FILES%, }. Add test file or mark (no-test)."
  else
    echo "TEST_FILE_MATCH|PASS|"
  fi
else
  echo "TEST_FILE_MATCH|PASS|"
fi

# ── Check 4: No placeholder tokens ──
PLACEHOLDERS=$(echo "$CLEAN" | grep -oE '__[A-Z_]{3,}__' | sort -u || true)

if [ -n "$PLACEHOLDERS" ]; then
  echo "NO_PLACEHOLDERS|FAIL|Found placeholder tokens: $(echo "$PLACEHOLDERS" | tr '\n' ' ')"
  ERRORS=$((ERRORS + 1))
else
  echo "NO_PLACEHOLDERS|PASS|"
fi

# ── Check 5: Affected Files non-empty ──
AF_FILES=$(echo "$AF_SECTION" | grep -cE '\S' || true)

if [ "$AF_FILES" -lt 1 ]; then
  echo "AFFECTED_FILES|FAIL|Affected Files section is empty"
  ERRORS=$((ERRORS + 1))
else
  echo "AFFECTED_FILES|PASS|"
fi

# ── Check 6: Valid classification ──
# First non-empty, non-comment line after ## Classification heading.
CLASSIFICATION=$(echo "$CONTENT" | sed -n '/^## Classification/,/^## /p' | sed '1d;$d' | sed '/^<!--/,/-->/d' | grep -m1 '\S' || true)
CLASSIFICATION=$(echo "$CLASSIFICATION" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')

VALID_CLASSIFICATIONS="fix feature refactor wont-do needs-info"
if echo "$VALID_CLASSIFICATIONS" | grep -qw "$CLASSIFICATION"; then
  echo "VALID_CLASSIFICATION|PASS|"
else
  echo "VALID_CLASSIFICATION|FAIL|Classification '${CLASSIFICATION}' is not one of: $VALID_CLASSIFICATIONS"
  ERRORS=$((ERRORS + 1))
fi

# ── Exit ──
if [ "$ERRORS" -gt 0 ]; then
  exit 1
fi
exit 0
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x .github/scripts/validate-spec.sh
```

- [ ] **Step 3: Test against a synthetic failing spec**

Create a temp spec with known violations and run the script:

```bash
cat > /tmp/test-bad-spec.md << 'EOF'
# Specification: Issue #999

## Classification
maybe

## Problem Analysis
After line 259 in apply.go, add the function.

## Affected Files

## Estimated Complexity
low
EOF

bash .github/scripts/validate-spec.sh /tmp/test-bad-spec.md
```

Expected: FAILs for REQUIRED_SECTIONS (missing Deliverables, Implementation Tasks, Test Strategy), NO_LINE_NUMBERS, AFFECTED_FILES, VALID_CLASSIFICATION.

- [ ] **Step 4: Test against a synthetic passing spec**

```bash
cat > /tmp/test-good-spec.md << 'EOF'
# Specification: Issue #999

## Classification
feature

## Deliverables
code

## Problem Analysis
The `GetEndpoints()` function is missing from the wireguard package.

## Implementation Tasks

### Task 1: Add GetEndpoints
- **File:** `pkg/wireguard/apply.go` (modify)
- **Where:** After `GetPeerTransfers()` function
- **What:** Add `GetEndpoints(iface string) (map[string]string, error)`
- **Detail:** Runs `wg show <iface> endpoints`, parses tab-delimited output.

### Task 2: Add test
- **File:** `pkg/wireguard/apply_test.go` (modify)
- **What:** Add `TestParseEndpointsOutput` table-driven test
- **Detail:** Cover two-peer, (none), empty, malformed cases.

## Affected Files
pkg/wireguard/apply.go       (modify)
pkg/wireguard/apply_test.go  (modify)

## Test Strategy
- `go build ./...` passes
- `go test ./pkg/wireguard/...` passes including new tests

## Estimated Complexity
low
EOF

bash .github/scripts/validate-spec.sh /tmp/test-good-spec.md
```

Expected: all PASS, exit 0.

- [ ] **Step 5: Commit**

```bash
git add .github/scripts/validate-spec.sh
git commit -m "feat: add validate-spec.sh for structural spec checks"
```

### Task 5: Create spec-validation.yml workflow

**Files:**
- Create: `.github/workflows/spec-validation.yml`

- [ ] **Step 1: Create the workflow file**

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
    # Skip in the template repo itself
    if: "!contains(github.repository, 'ai-pipeline-template')"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

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
        continue-on-error: true
        run: |
          bash .github/scripts/validate-spec.sh "${{ steps.find.outputs.spec_file }}" | tee /tmp/validation-results.txt

      - name: Auto-approve or flag
        if: always() && steps.find.outcome == 'success'
        uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          script: |
            const fs = require('fs');
            let raw = '';
            try {
              raw = fs.readFileSync('/tmp/validation-results.txt', 'utf8').trim();
            } catch (e) {
              raw = 'SCRIPT_ERROR|FAIL|validate-spec.sh produced no output';
            }
            const results = raw.split('\n').filter(l => l.includes('|'));

            const failures = results.filter(r => r.includes('|FAIL|'));
            const warnings = results.filter(r => r.includes('|WARN|'));
            const passed = failures.length === 0;

            const prNumber = context.issue.number;

            // Helper: safe label removal (ignore 404)
            async function removeLabel(name) {
              try {
                await github.rest.issues.removeLabel({
                  owner: context.repo.owner, repo: context.repo.repo,
                  issue_number: prNumber, name
                });
              } catch (e) { /* label not present — OK */ }
            }

            if (passed) {
              await removeLabel('spec-needs-fix');

              await github.rest.issues.addLabels({
                owner: context.repo.owner, repo: context.repo.repo,
                issue_number: prNumber, labels: ['approved-for-build']
              });

              let body = '**Spec validation passed.** Auto-approved for build.';
              if (warnings.length > 0) {
                body += '\n\n**Warnings (non-blocking):**\n' +
                  warnings.map(w => '- ' + w.split('|').slice(2).join('|')).join('\n');
              }
              await github.rest.issues.createComment({
                owner: context.repo.owner, repo: context.repo.repo,
                issue_number: prNumber, body
              });
            } else {
              await removeLabel('approved-for-build');

              await github.rest.issues.addLabels({
                owner: context.repo.owner, repo: context.repo.repo,
                issue_number: prNumber, labels: ['spec-needs-fix']
              });

              const body = '**Spec validation failed.**\n\n' +
                failures.map(f => {
                  const parts = f.split('|');
                  return `- **${parts[0]}**: ${parts.slice(2).join('|')}`;
                }).join('\n') +
                (warnings.length > 0
                  ? '\n\n**Warnings:**\n' + warnings.map(w => '- ' + w.split('|').slice(2).join('|')).join('\n')
                  : '');

              await github.rest.issues.createComment({
                owner: context.repo.owner, repo: context.repo.repo,
                issue_number: prNumber, body
              });

              core.setFailed('Spec validation failed — see PR comment for details');
            }
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/spec-validation.yml
git commit -m "feat: add spec-validation workflow with auto-approve"
```

### Task 6: Uncomment PR trigger in goose-build.yml

**Files:**
- Modify: `.github/workflows/goose-build.yml`

- [ ] **Step 1: Uncomment the pull_request trigger**

In `goose-build.yml`, uncomment the commented-out `pull_request:` trigger block so the `on:` block reads:

```yaml
on:
  pull_request:
    types: [labeled]
  workflow_dispatch:
```

Remove the comment block above it that says "pull_request trigger disabled until placeholders are replaced via init.sh".

- [ ] **Step 2: Update "Proposed Approach" reference to "Implementation Tasks"**

In the TASK_FOOTER heredoc inside the "Build Goose instructions" step, change:

```
          3. Implement the changes described in "Proposed Approach"
```

to:

```
          3. Implement the changes described in "Implementation Tasks"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/goose-build.yml
git commit -m "feat: enable PR trigger for Goose, update Implementation Tasks reference"
```

---

## Chunk 3: Initiative 1 — Fix init/deploy + live context injection

### Task 7: Add new prompts and replacement pairs to init.sh

**Files:**
- Modify: `init.sh`

- [ ] **Step 1: Add PROJECT_STRUCTURE and ARCHITECTURE_NOTES prompts**

After the `prompt PROJECT_DESC "Brief description"` line, add:

```bash
prompt PROJECT_STRUCTURE "Brief project structure (e.g. 'monorepo with pkg/ for libraries and cmd/ for CLI')"
prompt ARCHITECTURE_NOTES "Key architectural patterns (e.g. 'event-driven, repository pattern, CQRS')" ""
```

- [ ] **Step 2: Add replacement pairs**

After the `__SETUP_WITH__` pair in the PAIRS block, add:

```bash
PAIRS="${PAIRS}__PROJECT_STRUCTURE__|$(esc "$PROJECT_STRUCTURE")
"
PAIRS="${PAIRS}__ARCHITECTURE_NOTES__|$(esc "$ARCHITECTURE_NOTES")
"
```

- [ ] **Step 3: Commit**

```bash
git add init.sh
git commit -m "feat: add project structure and architecture prompts to init.sh"
```

### Task 8: Rewrite .goosehints with real template

**Files:**
- Modify: `.goosehints`

- [ ] **Step 1: Replace .goosehints content**

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

- [ ] **Step 2: Commit**

```bash
git add .goosehints
git commit -m "feat: rewrite .goosehints with real project context template"
```

### Task 9: Inject CLAUDE.md into Goose task instructions

**Files:**
- Modify: `.github/workflows/goose-build.yml`

- [ ] **Step 1: Add CLAUDE.md injection after task header**

In the "Build Goose instructions" step, after `cat > /tmp/goose-task.md << 'TASK_HEADER'` ... `TASK_HEADER` block and before `cat "$SPEC_FILE" >> /tmp/goose-task.md`, add:

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

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/goose-build.yml
git commit -m "feat: inject CLAUDE.md into Goose task instructions at runtime"
```

---

## Chunk 4: Verification

### Task 10: Validate all workflow YAML

- [ ] **Step 1: Check YAML syntax**

```bash
# Quick syntax check — python yaml.safe_load on each workflow
python3 -c "
import yaml, glob, sys
ok = True
for f in glob.glob('.github/workflows/*.yml'):
    try:
        yaml.safe_load(open(f))
        print(f'  OK: {f}')
    except yaml.YAMLError as e:
        print(f'  FAIL: {f}: {e}')
        ok = False
sys.exit(0 if ok else 1)
"
```

- [ ] **Step 2: Run actionlint if available**

```bash
actionlint .github/workflows/spec-validation.yml .github/workflows/copilot-triage.yml .github/workflows/goose-build.yml 2>&1 || echo "actionlint not installed — skipping"
```

- [ ] **Step 3: Run validate-spec.sh against both test specs again**

```bash
bash .github/scripts/validate-spec.sh /tmp/test-bad-spec.md && echo "UNEXPECTED PASS" || echo "Expected failure — OK"
bash .github/scripts/validate-spec.sh /tmp/test-good-spec.md && echo "Expected pass — OK" || echo "UNEXPECTED FAILURE"
```

- [ ] **Step 4: Verify init.sh placeholder coverage**

Check that every `__PLACEHOLDER__` in template files has a corresponding replacement pair in `init.sh`:

```bash
# Find all unique placeholders across template files
PLACEHOLDERS=$(grep -rhoE '__[A-Z_]{3,}__' --include='*.yml' --include='*.md' --include='.goosehints' . | grep -v '.git/' | sort -u)

# Check each is in init.sh PAIRS block
for p in $PLACEHOLDERS; do
  if grep -q "$p" init.sh; then
    echo "  OK: $p"
  else
    echo "  MISSING: $p"
  fi
done
```

- [ ] **Step 5: Final commit if any fixes needed**

Only if previous steps revealed issues that required fixes.
