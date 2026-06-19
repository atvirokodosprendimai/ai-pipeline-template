# feat: Weekly @wgmesh social drip

**Date:** 2026-06-19
**Type:** feat
**Depth:** Standard
**Origin:** `docs/brainstorms/2026-06-19-wgmesh-social-drip-requirements.md`

---

## Summary

A weekly GitHub Actions workflow that drafts one social post for `@wgmesh` (Bluesky + Mastodon) and pings the operator to review + publish. Clones the proven `daily-release-notes.yml` skeleton; swaps the output sink from Unsend-email to the **Mixpost draft API**, scopes the source to the **wgmesh repo only**, and adds a **ship-news-vs-evergreen** branch so cadence never goes dark. No unattended auto-publish.

---

## Problem Frame

`@wgmesh` is live but a one-post-then-silence account reads as dead. wgmesh rarely ships user-facing changes (most org effort is internal pipeline), so a purely shipping-driven drip would skip most weeks. We need sustainable weekly cadence that is curated (never a PR dump), product-facing (never plumbing), and human-gated (never botty auto-posts). See origin for full rationale.

---

## Key Technical Decisions

- **KTD1 — Reuse the digest skeleton.** Clone `.github/workflows/daily-release-notes.yml` structure (cron + `workflow_dispatch`, OpenRouter LLM via curl, best-effort guarded steps, sanitise gate). Extend-existing-pattern, minimal new surface.
- **KTD2 — Output sink = Mixpost draft, not email.** `POST {MIXPOST_BASE}/api/{ws}/posts` with `schedule:false` → draft to both accounts. Email becomes a *review ping*, not the deliverable. (Mixpost API verified live; see origin Dependencies.)
- **KTD3 — Source = wgmesh repo only.** `gh pr list -R atvirokodosprendimai/wgmesh --state merged --search merged:>=<7d>`; LLM classifies user-facing vs internal. Never org-wide.
- **KTD4 — Ship-vs-evergreen branch.** If ≥1 user-facing PR → highlight post; else → evergreen post from a rotating angle set, avoiding recent repeats via a small state file.
- **KTD5 — No unattended auto-publish.** Draft + ping only; operator publishes in Mixpost. (Honors origin decision 1.)
- **KTD6 — Secrets, not hardcoded IDs.** Mixpost token/workspace/account-ids + base URL via repo secrets/vars (`MIXPOST_*`). Account ids resolved at runtime via `GET /accounts` (avoids hardcoding 1/2).

---

## Requirements Traceability

- R1 (weekly cron + dispatch) → U1
- R2 (fetch wgmesh PRs + user-facing classify) → U2
- R3 (single highlight, ≤300 char) → U3
- R4 (evergreen fallback, no repeats) → U3, U4
- R5 (Mixpost draft, both accounts) → U5
- R6 (review ping email) → U5
- R7 (best-effort non-blocking) → all units
- R8 (sanitise gate before draft) → U3

---

## Implementation Units

### U1. Workflow skeleton + scheduling + config

**Goal:** New workflow file with weekly cron, manual dispatch, and env/secret wiring; mirrors the digest's job shape.
**Requirements:** R1, R7
**Dependencies:** none
**Files:** `.github/workflows/wgmesh-social-drip.yml` (new)
**Approach:** Copy the job scaffold from `.github/workflows/daily-release-notes.yml` (permissions, `runs-on`, `workflow_dispatch` inputs incl `dry_run`, env block). Cron `0 15 * * 4` (Thu 15:00 UTC). Env: `OPENROUTER_API_KEY`, `UNSEND_*`, `RELEASE_NOTES_FROM/TO` (reuse for ping), new `MIXPOST_BASE` (var, default `https://mixpost.infrawei.com/mixpost`), `MIXPOST_WORKSPACE` (secret/var), `MIXPOST_API_TOKEN` (secret), `WGMESH_REPO` (var, default `atvirokodosprendimai/wgmesh`), `GH_TOKEN`. `since_hours` input default `168`.
**Patterns to follow:** `daily-release-notes.yml` job/env/dispatch blocks.
**Test scenarios:** `Test expectation: none — scaffolding`; validated by U-wide dry-run + YAML/`bash -n` lint.
**Verification:** `python3 -c yaml.safe_load` parses; `gh workflow run` dispatchable with `dry_run=true`.

### U2. Collect wgmesh PRs + user-facing classification

**Goal:** Fetch the week's merged wgmesh PRs and have the LLM decide if any are user-facing.
**Requirements:** R2, R3, R7
**Dependencies:** U1
**Files:** `.github/workflows/wgmesh-social-drip.yml`
**Approach:** Step "Collect merged PRs": `gh pr list -R "$WGMESH_REPO" --state merged --search "merged:>=$since" --json number,title,url,labels,body`. LLM (OpenRouter `z-ai/glm-5.2`, JSON-strict) classifies each as `user_facing` bool + one-line "why a user cares"; emit `SHIP_NEWS=1|0` to `$GITHUB_ENV` + a shortlist file. `set -uo pipefail`; gh failure → warning + `SHIP_NEWS=0` (fall to evergreen). Filter out bot/`chore`/`heal`/plumbing by label+title before the LLM to save tokens.
**Patterns to follow:** digest collect step + its JSON-strict LLM call.
**Test scenarios:**
- Happy: 2 user-facing PRs in window → `SHIP_NEWS=1`, shortlist has both. Covers R2.
- All-internal: only heal/chore/supervisor PRs → `SHIP_NEWS=0`.
- Empty: no merged PRs → `SHIP_NEWS=0`, no error.
- Error: `gh` non-zero → warning, `SHIP_NEWS=0`, job continues.
**Verification:** dry-run logs show classification + correct `SHIP_NEWS`.

### U3. Content generation (highlight or evergreen) + sanitise

**Goal:** Produce one post body — highlight if ship-news, else evergreen — within Bluesky's 300-char limit, sanitise-gated.
**Requirements:** R3, R4, R8
**Dependencies:** U2
**Files:** `.github/workflows/wgmesh-social-drip.yml`, `company/social-drip-state.json` (new; read here)
**Approach:** Branch on `SHIP_NEWS`. **Highlight:** LLM picks the single most user-relevant change → punchy post (what + why + `https://wgmesh.dev`, release tag if present). **Evergreen:** read `company/social-drip-state.json` `recent_angles[]`; prompt LLM to pick an unused angle from a fixed set (differentiator / how-it-works / use-case / tip), grounded in `STRATEGY.md` + `FEATURE_MATRIX.md` positioning; output post + chosen `angle`. Enforce ≤300 chars (regen/trim if over). Pipe final body through `company/scripts/sanitise.sh`; fail-closed → skip draft + warn. Capture `POST_BODY` + `POST_ANGLE`.
**Patterns to follow:** digest LLM step; `company/scripts/sanitise.sh` gate per [[feedback_llm_emit_must_gate_on_sanitise]].
**Test scenarios:**
- Highlight happy: `SHIP_NEWS=1` → body references the change + link, ≤300 chars.
- Evergreen happy: `SHIP_NEWS=0` → body is an angle not in `recent_angles`, ≤300 chars.
- Rotation: `recent_angles` has 3 of 4 → picks the 4th.
- Over-limit: LLM returns 350 chars → trimmed/regenerated ≤300.
- Sanitise block: body with a secret-shaped string → sanitise fails → no draft, warning. Covers R8.
**Verification:** dry-run prints final body + char count + angle; sanitise runs.

### U4. Evergreen rotation state persistence

**Goal:** Record the angle used so future weeks don't repeat; commit back like other state files.
**Requirements:** R4
**Dependencies:** U3
**Files:** `.github/workflows/wgmesh-social-drip.yml`, `company/social-drip-state.json`
**Approach:** After a successful evergreen draft, append `POST_ANGLE` to `recent_angles` (keep last 4, FIFO) + `last_run` date; commit via branch+PR or fast-lane per repo state-commit convention (mirror supervisor-rank/pipeline-health state commits — protected main → branch+PR per [[feedback_state_commit_to_protected_main_fails]]). Only on real (non-dry-run) evergreen sends. Skip on ship-news weeks.
**Patterns to follow:** existing state-file commit workflows (`company/pipeline-health-state.json`, `supervisor-rank-state.json`).
**Test scenarios:**
- Append: evergreen post angle=tip → state gains `tip`, trims to last 4.
- No-op: ship-news week → state untouched.
- Dry-run: `dry_run=true` → no commit.
**Test expectation:** assert via dry-run log (no commit) + a state-file unit check if a test harness exists; else manual verify first live run.
**Verification:** after a live evergreen run, `social-drip-state.json` updated on main via PR.

### U5. Mixpost draft creation + review ping

**Goal:** Create the post as a Mixpost draft to both @wgmesh accounts and email the operator to review/publish.
**Requirements:** R5, R6, R7
**Dependencies:** U3
**Files:** `.github/workflows/wgmesh-social-drip.yml`
**Approach:** Resolve account ids: `GET {BASE}/api/{ws}/accounts` (Bearer `MIXPOST_API_TOKEN`, UA `Mozilla/5.0` for the Cloudflare gate) → collect all ids (avoid hardcoding 1/2). `POST {BASE}/api/{ws}/posts` body `{schedule:false, accounts:[ids], versions:[{account_id:0,is_original:true,content:[{body:POST_BODY,media:[]}],options:{mastodon:{sensitive:false}}}]}`. On 201, send review-ping via existing Unsend path (`POST {UNSEND_URL}/api/v1/emails`) with the post body + a `mixpost.infrawei.com` link to the drafts. `dry_run=true` → print body + skip POST + skip email. Best-effort: non-200 from Mixpost or Unsend → `::error`/`::warning` per severity; never post garbage.
**Patterns to follow:** Mixpost create-post API (origin Dependencies); digest Unsend send step + its UA/CF handling per [[feedback_cloudflare_1010_urllib_user_agent]].
**Test scenarios:**
- Happy: valid body → `POST /posts` 201 status `draft`; ping email accepted (200).
- Account resolve: `GET /accounts` returns 2 → both ids in `accounts[]`.
- Mixpost fail: 4xx/5xx → `::error`, no ping with false success.
- Dry-run: no POST, no email, body logged.
- Secrets unset: missing `MIXPOST_API_TOKEN` → warn + skip (graceful, like digest's unset-secret path).
**Verification:** live dry-run logs the would-be draft; one real run creates a visible draft in Mixpost + delivers the ping.

---

## Scope Boundaries

**In:** one weekly workflow → one draft (ship or evergreen) → both @wgmesh networks → review ping. Account-id resolution at runtime. Evergreen rotation state.

**Deferred to Follow-Up Work:**
- Auto-publish after review timeout (origin Q2; default manual now).
- A hand-curated evergreen backlog (LLM-generated for v1).
- Per-PR/release deep-linking beyond wgmesh.dev.

**Outside this product's identity (from origin):** X/LinkedIn (paid/dev apps), Reddit (Mixpost can't; n8n later), threads, media-in-posts, engagement/reply automation, analytics-driven topic choice, fully autonomous no-human posting.

---

## Risks & Dependencies

- **Mixpost token/workspace** must be set as secrets (`MIXPOST_API_TOKEN`, `MIXPOST_WORKSPACE`) — values exist (operator's private store), not yet in repo secrets. **Prereq before first live run.**
- **Cloudflare 1010:** Mixpost + OpenPanel hosts CF-gate non-browser UAs → all curl calls send `User-Agent: Mozilla/5.0` ([[feedback_cloudflare_1010_urllib_user_agent]]).
- **SES production access** already granted → review ping delivers.
- **Quality drift:** LLM evergreen could feel generic → human gate (KTD5) is the backstop; monitor first weeks.
- **State-commit to protected main** must go via branch+PR ([[feedback_state_commit_to_protected_main_fails]]).

---

## System-Wide Impact

New workflow only; no change to the daily digest or pipeline. Adds repo secrets (`MIXPOST_*`). New committed state file `company/social-drip-state.json`. Public-facing output (social posts) → sanitise gate is mandatory (R8).

---

## Sources & Research

- Origin: `docs/brainstorms/2026-06-19-wgmesh-social-drip-requirements.md`
- Pattern: `.github/workflows/daily-release-notes.yml` (digest skeleton, LLM call, Unsend send, CF-UA, graceful-unset)
- Mixpost API verified live this session (create-post, accounts, schedule); see private operator notes for token/workspace.
- `company/scripts/sanitise.sh` (public-emit gate).
