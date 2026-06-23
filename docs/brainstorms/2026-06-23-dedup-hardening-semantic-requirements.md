# Harden Build-Suggestion dedup with semantic similarity

**Date:** 2026-06-23 · **Scope:** Standard · **Status:** ready for `/ce-plan`
**Origin:** operator — "check all proposals, duplicates are being generated" → "harden dedup"
(live diagnosis on the Quackback board, 2026-06-22).

## Problem

The box-native observation loop floods the board with **reworded near-duplicate** Build
Suggestions — e.g. four variants of the same lead-capture idea ("Add email lead-capture form" /
"Add lead-capture email form" / "cloudroof.eu landing: add email lead-capture"). Root cause,
confirmed against the live code:

- The **fuzzy keyword dedup** (`observation.py` `is_duplicate`, 5-keyword/2-hit) runs against
  `build_dedup_corpus(inputs)`, whose corpus is `forge.list_open_issues()` — and for
  `QuackbackForge` that returns **only `Accepted for Build` posts** (KTD3). New suggestions sit in
  `Open` / `Open for Vote`, so the corpus is effectively **empty → the fuzzy layer never fires**.
- The **forge backstop** (`_find_duplicate_post`) *does* list all board posts (cross-status) but
  matches **exact normalized title only** — so any rewording slips it.

So the one layer that catches rewording is blind, and the layer that sees everything can't match
fuzzily. (A volume amplifier compounds it — see Out of scope.)

## Outcome

A reworded suggestion that means the same thing as an existing board post is recognized as a
duplicate and does **not** create a new post — restoring the dedup the bash loop had, but more
robust to paraphrase. The board stays one-post-per-intent instead of accreting near-dups.

## What we're building

The **forge backstop becomes the single authoritative dedup**, upgraded from exact-title to
**semantic cosine similarity** over all board posts:

- **Embed title + body** of the candidate and of existing posts; the candidate is a duplicate when
  its cosine similarity to any existing post is **≥ a configurable threshold**.
- **Conservative threshold**, config-tunable — bias against over-merging two genuinely distinct
  asks that happen to be topically close. Start high; loosen only if real duplicates slip.
- **Cache embeddings per post** (embed once when a post is created, persist it) — re-embedding
  every existing post on each create is the perf cost; the cache makes dedup one embedding (the
  candidate) plus a vector compare against stored vectors.
- **Provider:** z.ai embeddings, reusing the existing `ZAI_API_KEY` / z.ai host (no new credential).
- **Fail-closed-degrade:** if the embeddings call fails, fall back to the current exact-title match
  rather than skipping dedup — a degraded backstop beats none.
- **On duplicate:** unchanged — comment the new body on the existing post (accretes context); never
  silently drop the signal.

The now-redundant `observation.py` keyword layer (empty corpus under Quackback) is retired or
demoted to a cheap pre-filter — the authoritative guarantee moves to the forge, which sees every
post regardless of status.

## Scope boundaries

**In:** semantic dedup at the forge create backstop; per-post embedding cache; z.ai embeddings
wiring; conservative configurable threshold; fail-closed-degrade to exact-title; retire/demote the
empty-corpus keyword layer.

**Out of scope:**
- **The restart-amplifier** — observation runs a *full* create cycle on every box restart (no
  "ran recently" guard), and today's ~6 restarts drove the flood. That is the *volume* driver;
  perfect dedup makes re-runs create nothing new, but the wasted work (and embedding cost per
  re-eval) remains. Separate fix — a sibling brainstorm.
- **Wrong default board status** — new posts land in `Open` (a Quackback default), not
  `Open for Vote`. Off-decision-flow + off-roadmap. A one-call config fix, tracked separately.
- **Semantic dedup on the decision lane** — proposals there are comment-threaded, not new posts;
  dedup is a Build-Suggestion concern.

## Success criteria

- Two board posts whose titles/bodies express the same intent in different words are detected as
  duplicates; the second does not create a new post (it comments on the first).
- Two genuinely distinct asks that share keywords are **not** merged (precision — the over-merge
  guard the exact-title match implicitly gave up).
- An embeddings-API outage degrades to exact-title dedup, not to no dedup.
- Re-running observation against a board that already contains an intent creates zero new posts for
  that intent.

## Open questions (for planning)

- **z.ai embeddings endpoint/model — VERIFY.** Confirm the embeddings model id + endpoint reachable
  with `ZAI_API_KEY` (e.g. an `embedding-*` model on the z.ai host), the vector dimension, and the
  request/response shape — before building, mirroring the cutover's VERIFY discipline.
- **Threshold value + tuning.** The initial cosine cutoff and how it's tuned (a handful of known
  dup/non-dup pairs from the current board are a ready calibration set).
- **Embedding cache store.** Where the per-post vector lives (the pipeline store vs a side table)
  and how a post missing a cached vector is backfilled (embed-on-read once).
- **What exactly to embed.** Title only vs title + full brief vs title + leading brief — longer
  bodies cost more tokens and may dilute the title's intent signal.

## Dependencies / assumptions

- The live Quackback instance + bot key (present). The forge already pages all board posts for the
  cross-status dedup — the listing half is done; only the match changes.
- **Assumption (unverified):** z.ai exposes an embeddings endpoint usable with the existing key. If
  not, the provider decision reopens (a small local sentence-embedding model is the fallback) — the
  match mechanism (cosine over cached vectors) is provider-agnostic.

## Approach

**Extend, not net-new:** keep `_find_duplicate_post`'s all-posts cross-status listing; swap its
matcher from normalized-title equality to cosine-over-embeddings, backed by a per-post vector cache,
with exact-title as the degrade path. The observation keyword dedup is removed or demoted once the
forge owns the guarantee.
