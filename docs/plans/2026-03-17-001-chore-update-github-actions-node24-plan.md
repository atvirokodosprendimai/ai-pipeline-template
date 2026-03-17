---
title: "Update GitHub Actions to Node.js 24"
type: chore
status: active
date: 2026-03-17
---

# Update GitHub Actions to Node.js 24

Node.js 20 actions are deprecated. GitHub will force Node.js 24 starting June 2nd, 2026. Update `actions/checkout` from v4 to v6 and `actions/github-script` from v7 to v8 across all workflow files.

## Acceptance Criteria

- [ ] All `actions/checkout@v4` → `actions/checkout@v6`
- [ ] All `actions/github-script@v7` → `actions/github-script@v8`
- [ ] Workflows in `.github/workflows/` updated
- [ ] Workflows in `.github/workflow-templates/` updated
- [ ] No deprecation warnings on next push

## Files to Update

| File | checkout | github-script |
|------|----------|---------------|
| `.github/workflows/observation-loop.yml` | v4→v6 | — |
| `.github/workflows/spec-validation.yml` | v4→v6 | v7→v8 (x2) |
| `.github/workflows/sync-labels.yml` | v4→v6 | v7→v8 |
| `.github/workflows/approve-build.yml` | — | v7→v8 (x2) |
| `.github/workflows/copilot-triage.yml` | — | v7→v8 |
| `.github/workflows/copilot-undraft.yml` | — | v7→v8 |
| `.github/workflow-templates/goose-build.yml` | v4→v6 | v7→v8 (x3) |
| `.github/workflow-templates/board-sync.yml` | — | v7→v8 |

**Totals:** 4x checkout, 11x github-script

## Version Details

| Action | From | To | Breaking Changes |
|--------|------|----|-----------------|
| `actions/checkout` | v4 | v6 | Creds persisted to separate file (not `.gitconfig`). Min runner v2.327.1. |
| `actions/github-script` | v7 | v8 | Node 24 runtime only — no API changes. Min runner v2.327.1. |

## MVP

Two `sed` commands per directory:

```bash
sed -i 's|actions/checkout@v4|actions/checkout@v6|g' .github/workflows/*.yml
sed -i 's|actions/github-script@v7|actions/github-script@v8|g' .github/workflows/*.yml
sed -i 's|actions/checkout@v4|actions/checkout@v6|g' .github/workflow-templates/*.yml
sed -i 's|actions/github-script@v7|actions/github-script@v8|g' .github/workflow-templates/*.yml
```

## Risk

Low. `github-script@v8` has no API changes — only the Node runtime bumps. `checkout@v6` credential change is irrelevant (we don't read `.gitconfig` directly). GitHub-hosted runners already support v2.327.1+.
