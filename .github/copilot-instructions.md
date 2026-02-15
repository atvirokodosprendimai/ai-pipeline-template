# Copilot Instructions for __PROJECT_NAME__

## Project Overview

__PROJECT_NAME__ is a __LANGUAGE__-based project. __PROJECT_DESCRIPTION__

## Code Style

- **Language**: __LANGUAGE__ __LANGUAGE_VERSION__
- **Formatting**: `__FORMAT_CMD__`

<!-- TODO: Add your project-specific code style guidelines here -->
<!-- Examples: error handling conventions, naming conventions, etc. -->

## Project Structure

<!-- TODO: Describe your project's directory structure -->
<!-- Example:
    src/
    ├── components/   # UI components
    ├── services/     # Business logic
    ├── models/       # Data models
    └── utils/        # Shared utilities
-->

## Build & Test

```
Build:  __BUILD_CMD__
Test:   __TEST_CMD__
Lint:   __LINT_CMD__
Format: __FORMAT_CMD__
```

## When Triaging Issues (Spec-Only Mode)

When asked to triage an issue and write a specification:

1. **Do NOT write implementation code** - only produce a spec document
2. Create the spec file at `specs/issue-{NUMBER}-spec.md`
3. Use this template for the spec:

```
# Specification: Issue #{NUMBER}
## Classification
<!-- One of: fix, feature, refactor, wont-do, needs-info -->
## Problem Analysis
## Proposed Approach
## Affected Files
## Test Strategy
## Estimated Complexity
<!-- One of: low, medium, high -->
```

4. Open as a PR titled: `spec: Issue #{NUMBER} - {brief description}`
5. Target the `main` branch
6. Include only the spec file - no code changes

## Security Considerations

<!-- TODO: Document security considerations for your project -->
<!-- Examples: secret handling, input validation, authentication, etc. -->
- Never hardcode secrets, keys, or tokens
