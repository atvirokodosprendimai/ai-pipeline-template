# Weekly @wgmesh Social Drip — Requirements

**Date:** 2026-06-19
**Status:** Ready for planning
**Scope:** Standard feature (new scheduled workflow, mirrors the daily release-notes digest)

## Problem

`@wgmesh` is now live on Bluesky + Mastodon (via the InfraWei Mixpost Pro instance), with profiles dressed and a first post out. But a new account with one post and then silence reads as abandoned. We need a sustainable weekly cadence that keeps the account alive **without** turning it into a botty changelog or posting internal pipeline noise to the public.

Two hard realities shape this:
1. The **daily release-notes digest** is an exhaustive internal PR list — the opposite of what a follower wants. Social must be curated and human-sounding.
2. wgmesh **rarely ships user-facing changes** most weeks (the org's effort skews to pipeline/infra). A purely shipping-driven drip would skip most weeks → dead account.

## Decisions (resolved this brainstorm)

1. **Publish gate:** Generate as a **Mixpost draft**; human (operator/lempa) reviews + publishes. **No unattended auto-publish.** Protects a public account from awkward/incorrect posts.
2. **Post shape:** **Single curated highlight** — one punchy post (what + why a user cares + link), not a roundup or thread. Reads like a person wrote it.
3. **Quiet weeks → evergreen fallback:** If there's no user-facing shipping news, draft an **educational/evergreen** post instead (how-it-works, a differentiator like the "works offline on LAN" post, a use-case). The generator picks: ship-news if present, else evergreen. Cadence never goes dark.
4. **Source/filter:** wgmesh **product repo only** (merged PRs / release notes), filtered to **user-facing** changes. Never org-wide plumbing, never the pipeline repo.

## Requirements

- **R1.** Runs weekly on a schedule (cron) + manual `workflow_dispatch`, like `daily-release-notes.yml`.
- **R2.** Pulls the past week's merged PRs from the wgmesh repo; an LLM judges which (if any) are **user-facing** (a feature, fix, or capability a wgmesh user would notice) vs internal.
- **R3.** If ≥1 user-facing change: generate a single highlight post — lead with the most relevant change, plain-English "what shipped + why it matters", link to wgmesh.dev or the repo. Stay within **Bluesky's 300-char limit** (Mastodon allows more; one body serves both).
- **R4.** If no user-facing change: generate an **evergreen** post from a rotating set of angles (differentiator, how-it-works, use-case, tip). Avoid repeating recent evergreen topics.
- **R5.** Create the post as a **draft** via the Mixpost API (`POST /api/<ws>/posts`, `schedule:false`), targeting both connected @wgmesh accounts (Bluesky id 1, Mastodon id 2).
- **R6.** **Notify** the operator the draft is ready to review + publish — include the draft text + a Mixpost link. Reuse the existing Unsend send path (transactional email).
- **R7.** Best-effort + non-blocking: any failure (no PRs, LLM error, Mixpost/API error) logs a warning and does not hard-fail or post garbage. Same discipline as the digest.
- **R8.** Public-safety: run generated copy through the existing sanitise gate before drafting (no secrets, no internal/PII, no exact revenue) — it's headed to a public account.

## Scope boundaries

**In:**
- One weekly workflow producing one draft post (ship-news or evergreen) to @wgmesh on Bluesky + Mastodon.
- Human-approve publish loop via Mixpost + an email ping.

**Out (deferred):**
- Auto-publish after a review timeout (see Outstanding Questions).
- X / LinkedIn (need paid/dev apps), Reddit (Mixpost can't; n8n later).
- Threads, image/media in posts, engagement/reply automation, analytics-driven topic selection.
- Fully autonomous (no-human) posting — explicitly rejected for a public account.

## Success criteria

- @wgmesh posts ~1×/week with **zero** weeks of unintended silence and **zero** pipeline-plumbing/changelog-dump posts.
- Each post is something the operator would publish as-is or with a tiny edit (low review friction).
- Operator effort per week ≈ a glance + one click (or a skip).

## Dependencies / assumptions

- Mixpost Pro API: token + workspace `e134432b-…`, accounts connected (Bluesky id 1, Mastodon id 2). **Verified live this session.**
- Unsend transactional email (for the review ping) — already wired for the digest. SES now in production access.
- Reuses the digest workflow pattern (`daily-release-notes.yml`): cron + LLM-via-OpenRouter + best-effort steps.
- **Assumption:** the wgmesh repo's merged PRs are a sufficient signal for "what shipped"; release-notes/tags optional refinement.
- **Assumption:** evergreen angles can be LLM-generated from wgmesh's positioning (STRATEGY.md / FEATURE_MATRIX.md) without a hand-curated backlog — to validate during planning.

## Outstanding questions (for planning)

- **Q1.** Where does the workflow live + run — the template repo's GitHub Actions (like the digest), or the box? (Leaning: template Actions, same as digest.)
- **Q2.** Auto-publish after N hours if not rejected, or always manual publish? (Default: manual; revisit if review becomes a bottleneck.)
- **Q3.** Cron day/time — e.g. Tue or Thu ~15:00–16:00 UTC for EU+US dev overlap.
- **Q4.** Evergreen topic rotation — track recently-used angles where? (state file vs let LLM vary by week.)
- **Q5.** Should ship-news posts also link the specific PR/release, or just wgmesh.dev?

## Recommended approach

Reuse, don't invent: clone the `daily-release-notes.yml` skeleton (cron, OpenRouter LLM call, best-effort guards, sanitise gate) but swap the output sink from Unsend-email to **Mixpost-draft**, the source to **wgmesh repo only**, and add the **ship-news-vs-evergreen** branch. The email step becomes a *review ping*, not the deliverable. This is an **extend-existing-pattern** build, low new surface.
