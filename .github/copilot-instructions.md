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
