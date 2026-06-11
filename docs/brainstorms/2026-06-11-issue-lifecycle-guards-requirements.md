# Issue Lifecycle Guards — Requirements

**Date:** 2026-06-11
**Status:** Ready for planning
**Scope:** Deep — feature (lifecycle/architecture change to the wgmesh autonomous pipeline)
**Origin:** ce-debug investigation of the "false-completion" defect (session 2026-06-11)

## Problem

The pipeline reprocesses issues that are already resolved and mis-closes issues that aren't.
Traced root causes:

1. **No resolved-guard on claim.** `pipeline/wgmesh_pipeline/github/reconcile.py` claims every
   open issue (`list_open_issues`) with no check for an existing merged resolution. Issues that
   were resolved months ago and **operator-reopened** (#510 — spec #511 merged 2026-04-12,
   reopened 04-29; #540 — impl #544 merged 2026-04-29, reopened 05-05) got re-specced and
   re-implemented, producing dangling duplicate PRs (#688/#719, #690/#717).
2. **Stale-merged-PR re-close.** `.github/workflows/close-resolved-issues.yml` closes an issue
   `state_reason: completed` when it finds *any* merged `impl: Issue #N` PR, blind to whether the
   issue was reopened *after* that merge for new work. #540's April merge re-closed it on 06-10
   while its new impl #717 was still open.
3. **Diffuse, unexplained close authority.** Multiple workflows close issues COMPLETED via the
   `PUSH_TOKEN` principal (close-resolved-issues, verify-comment-close, e2e-verify-close). #584
   closed COMPLETED on 06-10 with **no merged PR of any kind** — the responsible closer is not
   yet identified.

Net effect: convergence accounting is corrupted (issues look done that aren't, and resolved
issues spawn dangling work), and it blocked the first clean autonomous merge by destroying
candidate subjects.

## Goal

The box processes an issue at most once to resolution, and an issue closes COMPLETED only on a
real current-cycle resolution signal — while still letting the operator deliberately request
rework.

## Decisions (resolved in brainstorm)

- **Claim model: reopen + explicit rework marker.** An issue with a merged resolution is
  re-claimable by the box **only** if it is open AND carries an explicit `needs-rework` label
  AND has no open bot PR. A bare reopen (no marker) is invisible to the box — it will not
  re-spec or re-implement. New work without a marker means a new issue.
- **Close authority is consolidated and fenced.** One designated closer sets `COMPLETED`,
  keyed on a merged impl PR for the *current* work cycle (a merge that post-dates the latest
  reopen, or — equivalently under the marker model — a merge while no `needs-rework` is active).
  Other autonomous closers must not set COMPLETED on stale or non-merge signals.
- **#584 handling: fence, don't block.** The exact closer that mis-closed #584 is fenced out by
  the close-authority consolidation even though it is not fully root-caused. Locking down who may
  close is the fix; a full #584 forensic is not a blocker (see Outstanding Questions).
- **`needs-rework` is operator-applied.** The box does not auto-detect "reopened for new work";
  the operator labels the issue. Accepted as the explicit, low-magic control surface.

## Requirements

- **R1** Reconcile skips a resolved issue (one with a merged impl/spec resolution, or box state
  already `merged`) unless it is open, labelled `needs-rework`, and has no open bot PR.
- **R2** A bare reopen (no `needs-rework`) never triggers claim, spec, or implement.
- **R3** Applying `needs-rework` to a reopened resolved issue makes it claimable for a fresh cycle;
  the box treats it as new work (new spec/impl branch cycle) and clears the marker when the new
  cycle resolves.
- **R4** Exactly one workflow may close an issue `state_reason: completed`, and only on a merged
  impl PR belonging to the current cycle. Stale-merged-PR matches (a merge predating the latest
  reopen) do not close.
- **R5** No autonomous path closes an issue COMPLETED on a non-merge signal (the #584 class is
  fenced out).
- **R6** One-time cleanup: the existing dangling duplicate PRs (#688/#719, #690/#717, #668/#722)
  are closed with a goal-citing reason, since their issues are resolved or marker-less.

## Success criteria

- A resolved-then-reopened issue without `needs-rework` sits untouched: no new spec/impl PR, no
  re-close churn.
- Labelling such an issue `needs-rework` drives exactly one fresh cycle and the issue closes only
  when that cycle's impl PR merges.
- No issue closes COMPLETED without a current-cycle merged impl PR.
- After cleanup, zero dangling bot PRs against resolved/closed issues.

## Scope Boundaries

**In scope:** reconcile claim guard (R1-R3), close-authority consolidation + stale-match fix
(R4-R5), one-time dangling-PR cleanup (R6).

### Deferred for later
- Auto-detecting "reopened for new work" without a manual marker (the timestamp model was
  considered and set aside as too silent — revisit only if the manual marker proves burdensome).
- The first autonomous impl merge itself — needs a fresh low-risk issue, tracked separately; not
  this lifecycle work.

### Outside this change
- The verification gate, ggshield, routing, cost capture — all working, untouched.
- The PUSH_TOKEN→app-token migration (separate OPEN track), though close-authority consolidation
  should prefer the durable principal where it touches the same workflows.

## Dependencies / Assumptions

- Assumes "resolved" is detectable from a merged impl PR (title/branch convention `bot/impl-N` /
  `impl: Issue #N`) and/or the box's Turso state. Planning confirms the canonical signal.
- Assumes the operator will apply `needs-rework` when they want a redo (replaces the current
  bare-reopen behavior they used on #510/#540).

## Outstanding Questions (for planning)

1. **#584 closer identity.** Fenced by R5, but worth a bounded trace at plan time: which workflow
   (suspect verify-comment-close on a stray issue_comment) set COMPLETED with no merged PR, and
   does the consolidation actually remove its ability to?
2. **Canonical resolved-signal.** Merged-PR search vs box Turso state vs both — which is
   authoritative for R1/R4, and how do they reconcile when they disagree.
3. **Marker lifecycle.** Who clears `needs-rework` and when (on new-cycle claim? on new merge?) so
   it can't get stuck and re-trigger.
