# Specification: Issue #746

## Classification
feature

## Deliverables
code

## Problem Analysis

Open issues with no `type: *` label are invisible to every downstream pipeline workflow that filters by label (`copilot-triage.yml`, `spec-merged-build.yml`, etc.). The current `pipeline-health.yml` self-healing logic only heals issues that **already carry a pipeline label** (`needs-triage`, `copilot-triaging`, `approved-for-build`). Issues that were filed without any label — or filed before label-sync ran — silently rot: `strategy-audit.yml` computes `ACTIVE_STUCK_ISSUES` as `needs-human` count + cooldown count, so zero-label issues never surface.

Concretely:
- `copilot-triage.yml` triggers on `labeled` event for `needs-triage`, `fn:dev`, or `bug` — it will never fire for a label-free issue.
- `pipeline-health.yml` checks `--label needs-triage` which also misses zero-label issues.

The fix requires a new scheduled workflow (`triage-watchdog.yml`) that performs this sweep against the seeded product repo (`atvirokodosprendimai/wgmesh`), applies `needs-triage` to trigger triage, escalates to `needs-human` after 7 days, and adds a `triage-sla-breach` label to make these issues visible in the stuck-state dashboard. A companion label definition and a type-namespace policy document complete the set.

## Implementation Tasks

### Task 1: Add `triage-sla-breach` label to `.github/labels.yml`

- **File:** `.github/labels.yml` (modify)
- **Where:** After the `needs-human` entry in the `# === Health Monitoring ===` section
- **What:** Append a new label entry with `name: triage-sla-breach`, `color: "FFA500"`, `description: "Issue open >24h with no type: * label — triage SLA breached"`
- **Detail:** This label is applied by `triage-watchdog.yml` to mark the breach and is a prerequisite for surfacing a distinct stuck-state bucket in the pulse dashboard. The `sync-labels.yml` workflow syncs labels from this file on push to `main`, so the label will be created in the template repo automatically; the watchdog also creates it on-demand in the target repo using `gh label create --force`.

### Task 2: Create `triage-watchdog.yml` scheduled workflow

- **File:** `.github/workflows/triage-watchdog.yml` (create)
- **Where:** New file
- **What:** Add a workflow named `Triage SLA Watchdog` that runs on schedule (`0 */6 * * *`) and on `workflow_dispatch`, targeting `atvirokodosprendimai/wgmesh` (via `env.TARGET_REPO`).
- **Detail:** The workflow has a single job `watchdog` with the following steps:

  1. **Ensure labels exist in target repo** — using `GH_TOKEN: ${{ secrets.PUSH_TOKEN }}`, run `gh label create needs-triage --color FBCA04 --description "..." --force` and `gh label create triage-sla-breach --color FFA500 --description "..." --force` to guarantee both labels exist in the target repo before use (idempotent, `--force` updates if present).

  2. **Sweep for 24h no-type issues** — compute a 24h cutoff with dual-platform `date` (same pattern as `pipeline-health.yml`). Run `gh issue list --repo "$TARGET_REPO" --state open --limit 200 --json number,title,createdAt,labels` and pipe through `jq` to select issues where `createdAt < cutoff` AND `[.labels[].name | test("^type: ")] | length == 0` (the regex `^type: ` matches all canonical type labels such as `type: bug`, `type: feature`, `type: refactor`, `type: docs`). For each matching issue that does NOT already have `triage-sla-breach`:
     - Post a comment: `"⚠️ Triage SLA breach — this issue has been open for over 24h with no \`type:*\` label. Adding \`needs-triage\` to route it through the automated triage pipeline. /cc maintainers."`
     - Add labels `needs-triage` and `triage-sla-breach` via `gh issue edit --add-label`.
     - Increment a counter `BREACHES_FOUND`.

  3. **Escalate 7-day repeat offenders** — compute a 7-day cutoff. Re-query open issues where `createdAt < 7d_cutoff` AND no `type: *` label (using the same `^type: ` regex) AND already has `triage-sla-breach` but does NOT have `needs-human`. For each match:
     - Post a comment: `"🚨 Triage SLA escalation — this issue has been open for 7+ days with no \`type:*\` label. Escalating to \`needs-human\` for manual review."`
     - Add label `needs-human` via `gh issue edit --add-label`.
     - Increment a counter `ESCALATIONS`.

  4. **Print summary** — echo `"Watchdog complete: $BREACHES_FOUND breach(es) labeled, $ESCALATIONS escalation(s) created."` so the run log is self-documenting.

  Use `GH_TOKEN: ${{ secrets.PUSH_TOKEN }}` on all steps that call the GitHub CLI. Add `permissions: issues: write` at the workflow level. Add `concurrency: group: triage-watchdog, cancel-in-progress: false` to prevent overlapping runs.

### Task 3: Document type-namespace policy in `.github/copilot-spec.md`

- **File:** `.github/copilot-spec.md` (create)
- **Where:** New file
- **What:** Create a Markdown policy document titled `# Type-Namespace Policy` that seeded products can reference.
- **Detail:** The document must state:
  - Every issue **must** receive exactly one `type: *` label during triage. The canonical set is `type: bug`, `type: feature`, `type: refactor`, `type: docs` (matching the entries in `.github/labels.yml`). All four names share the `type: ` prefix (note: space after colon), which is the pattern checked by `triage-watchdog.yml`.
  - Issues without a `type: *` label after 24h are flagged by `triage-watchdog.yml` with `needs-triage` + `triage-sla-breach`.
  - Issues without a `type: *` label after 7 days are escalated with `needs-human`.
  - Copilot triage agents (via `copilot-triage.yml`) are responsible for applying the correct `type: *` label as part of spec creation.
  - The document should include a table of the four canonical `type: *` labels with their meanings, matching the descriptions in `.github/labels.yml`.

### Task 4: Update `strategy-audit.yml` to count triage-SLA breaches in stuck issues

- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** In the step named `Compute self-heal rate and active stuck issues` (the step that sets `ACTIVE_STUCK_ISSUES` in `$GITHUB_ENV`)
- **What:** Add a `triage_sla_count` variable that counts open issues in `TARGET_REPO` carrying the `triage-sla-breach` label, then include it in the `active_stuck_issues` calculation.
- **Detail:** After the existing line that computes `needs_human_count` using `gh issue list --label needs-human`, add a parallel line: `triage_sla_count=$(gh issue list --repo "$TARGET_REPO" --state open --label triage-sla-breach --limit 100 --json number | jq 'length')`. Then change the `active_stuck_issues` line to `active_stuck_issues=$((needs_human_count + cooldown_count + triage_sla_count))`. This surfaces triage-SLA breaches as a distinct stuck-state bucket in the pulse without modifying any other audit logic.

## Affected Files

`.github/labels.yml`                        (modify)
`.github/workflows/triage-watchdog.yml`     (new, no-test)
`.github/copilot-spec.md`                   (new, no-test)
`.github/workflows/strategy-audit.yml`      (modify, no-test)

## Test Strategy

- `gh workflow run triage-watchdog.yml` on a test repo that has at least one open issue with no `type: *` label and age > 24h. Verify:
  - The issue receives the `needs-triage` label.
  - The issue receives the `triage-sla-breach` label.
  - A comment containing "Triage SLA breach" is posted on the issue.
- Manually create an open issue in `wgmesh` with no labels and run the watchdog via `workflow_dispatch`. Expect the issue to be labeled and commented within one run.
- Verify that any existing open issue in `wgmesh` without a `type: *` label and older than 24h is labeled and commented on within one watchdog run.
- Check `strategy-audit.yml` run: `ACTIVE_STUCK_ISSUES` should increase by the number of `triage-sla-breach` issues found, confirming the new counter is included.
- For escalation: artificially create an open issue older than 7 days with `triage-sla-breach` (no `type: *` label, no `needs-human`) and verify the watchdog adds `needs-human` and posts an escalation comment.

## Estimated Complexity
medium (3-5 files)
