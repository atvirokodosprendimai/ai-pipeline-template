---
title: "GitHub Actions validates all workflow YAML on every push — placeholder values cause persistent failures"
category: integration-issues
date: 2026-03-17
tags: [github-actions, workflow-validation, template-repos, placeholders, ci-cd]
problem_type: integration_issue
components: [".github/workflows/", "init.sh", "goose-build.yml", "board-sync.yml"]
severity: medium
---

## Problem

Template repos using `__PLACEHOLDER__` tokens in GitHub Actions workflow files get persistent "Invalid workflow file" failures on every push. These show as failed runs in the Actions tab and spam email/notification channels.

**Exact error:**
```
Invalid workflow file: .github/workflows/goose-build.yml#L1
(Line: 120, Col: 15): Expected format {org}/{repo}[/path]@ref. Actual '__SETUP_ACTION__'
```

## Root Cause

GitHub validates **all YAML files** in `.github/workflows/` on every push event, regardless of:
- Whether the workflow has a `push` trigger (it doesn't need one)
- Whether the job has an `if` condition that would skip it
- Whether the trigger is commented out

Specifically, `uses:` field values are validated against the `{org}/{repo}[/path]@ref` format at parse time, before any runtime evaluation. Placeholder values like `__SETUP_ACTION__` fail this static validation.

Additional discovery: the `secrets` context is **not available** in job-level or step-level `if` expressions. It can only be used in `env:` or `with:` blocks. Using `secrets.FOO` in an `if:` produces a separate validation error: `Unrecognized named-value: 'secrets'`.

## Solution

Move workflow files containing `uses:` placeholders out of `.github/workflows/` into a staging directory (`.github/workflow-templates/`). Have the init script move them into `workflows/` after all placeholders are replaced.

**Directory structure (template repo):**
```
.github/
  workflows/              ← only valid, placeholder-free workflows
    copilot-triage.yml
    spec-validation.yml
    observation-loop.yml
  workflow-templates/      ← workflows with placeholders (not validated by GitHub)
    goose-build.yml        ← has uses: __SETUP_ACTION__
    board-sync.yml         ← has env: __PROJECT_ID__
```

**In `init.sh`, after placeholder replacement:**
```bash
if [ -d ".github/workflow-templates" ]; then
  for tmpl in .github/workflow-templates/*.yml; do
    mv "$tmpl" ".github/workflows/$(basename "$tmpl")"
  done
  rmdir .github/workflow-templates
  echo "    Activated workflow templates"
fi
```

**For the `secrets` issue**, move the check to where secrets are accessible (inside `env:` or `with:`), or remove it entirely if other guards (like placeholder checks on `env` variables) already prevent the job from running in unconfigured repos.

## What Didn't Work

1. **Guard jobs with `if: always()`** — GitHub marks runs as "failure" when all real jobs skip. Adding a lightweight always-succeeding guard job makes skipped runs show green, but doesn't prevent the static YAML validation failures (those happen before any job runs).

2. **Commenting out triggers** — GitHub still validates the entire file even when all triggers are commented out. The `workflow_dispatch` trigger being active was enough.

3. **Commenting out the `uses:` step** — Having `init.sh` uncomment it after setup adds fragile sed logic. The staging directory approach is cleaner.

4. **`secrets` in `if` expressions** — `secrets` context is not available in `if` at any level (job or step). This is a GitHub Actions limitation, not a bug.

## Prevention

- **Never put placeholder values in `uses:` fields** of workflows that live in `.github/workflows/`. Either use a staging directory or use valid defaults that init replaces.
- **Never use `secrets` in `if` expressions.** Use `env:` to pass secret values into steps, or use other guards (like checking for placeholder strings in environment variables).
- **Test workflow validity locally** with `actionlint` before pushing, if available.
- **Keep workflows with placeholders isolated** until they're fully configured.
