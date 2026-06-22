# feat: rich PM-grade Build Suggestion briefs — generate + carry + build from the body

**Date:** 2026-06-22 · **Type:** feat · **Depth:** Medium
**Origin:** operator — "I want good suggestions, with pros/cons, ROI, etc, like a normal
product manager feature description" (Quackback cutover follow-on).

---

## Problem

The box builds from the **title only**. The assess loop emits `{title, body, labels}`, but
(1) the prompt gives the `body` no structure, so it's thin, and (2) the build path drops the
body entirely — `reconcile_quackback` carries title-only (KTD10 PII fence), and the spec
recipe (`wgmesh-triage-spec.yaml`) takes `issue_number` + `issue_title`, never a body. So a
rich brief can't reach the builder, and Accepting a decision-shaped post specs from a bare
title → thin/wrong build. The cutover gated the *decision*; it didn't make the *brief* usable.

## Goal

End-to-end rich briefs: the box **generates** PM-grade Build Suggestions (Problem, Pros,
Cons, ROI/Impact, Proposed Approach, Acceptance) into the post body, the body is **carried**
into the build (sanitise-walled, resolving KTD10 by sanitising not dropping), and the spec
**builds from the brief**, not the title alone.

## Units

### U1 — Generate PM-grade bodies (assess prompt)
**File:** `pipeline/wgmesh_pipeline/observation_gather.py` (the assess recipe prompt).
Require the `body` of every `issues_to_create` item to be a structured feature brief with
exact sections: `## Problem`, `## Proposed Solution`, `## Pros`, `## Cons`, `## ROI / Impact`
(effort vs the metric it moves), `## Acceptance Criteria`. Keep public-repo-safe (no PII /
revenue). Body already flows `create_issue → create_post → board`, so founders see the brief
immediately. Prompt-only change.
**Test:** assert the prompt declares the required body sections (characterization on the
recipe text). `Covers: founders see PM-grade briefs on the board.`

### U2 — Carry the body into the build (store + reconcile, sanitise-walled)
**Files:** `state/migrations/0004_issue_body.sql` (add `body TEXT` to issues),
`state/store.py` (`IssueRecord.body`, `upsert_issue(body=…)`), `github/reconcile.py`
(`reconcile_quackback` reads `post["content"]` → sanitise → store as body; fail-closed on
sanitise error — skip that one ingest, never crash the tick).
KTD10 resolved: the body is **sanitised at ingest** (box-authored bodies already pass the
create-time wall; founder-edited board bodies get the wall here) instead of dropped.
github path stays title-only (rollback path; `body` defaults to "").
**Test:** reconcile_quackback stores the post content as body; a body that fails sanitise is
skipped (not stored, tick survives); migration adds the column; IssueRecord round-trips body.
`Covers: the brief survives to spec time.`

### U3 — Build from the brief (spec node + recipe)
**Files:** `graph/nodes/spec.py` (pass `issue_body` param from `issue.body`),
`recipes/wgmesh-triage-spec.yaml` (declare `issue_body` param, use it in the prompt:
"Full brief follows — build from it: {{ issue_body }}"; tolerate empty).
**Test:** spec passes `issue_body` from the store row; empty body → recipe still valid
(github fallback). `Covers: the builder specs from the brief, not the title.`

## Scope
- **In:** quackback live path end-to-end (generate→carry→build), sanitise wall on the body.
- **Out:** github path body-carry (rollback-only, stays title-only); comment / two-way
  steering (U10/U11 — larger follow-on); vote-rerank.

## Sequencing
U1 independent (prompt). U2 before U3 (spec reads what reconcile stored). All TDD.
