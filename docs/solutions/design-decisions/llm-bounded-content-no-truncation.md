---
title: "Length-bounded LLM content (social posts) without mid-meaning truncation"
category: design-decisions
date: 2026-06-19
tags: [llm, prompt, social, mixpost, social-drip, content-generation, openrouter]
---

## Problem

The weekly `@wgmesh` social drip (`.github/workflows/wgmesh-social-drip.yml`) generated a Bluesky/Mastodon post that was cut mid-sentence — *"…so you can run wgmesh edge nodes in production for a month and walk away…"* — and omitted the required link. The post read as botty/incomplete on a public account.

## Root cause

Two independent causes, both common when an LLM must write under a hard character cap:

1. **The prompt only said "concise / ≤300 chars".** The model maxed the budget and *trailed off* with its own ellipsis instead of finishing the thought, and it dropped the mandatory `wgmesh.dev` link because the prompt never made the link non-negotiable.
2. **The truncation backstop destroyed meaning.** `trim_post` hard-cut at 280 chars and appended `"..."`:
   ```python
   cut = text[: limit - 3].rstrip()
   return cut + "..."   # cuts mid-word, fabricates an ellipsis
   ```
   (In this incident the LLM output was already <280, so the ellipsis was the model's own — but the backstop would have made it worse on longer output.)

## Guidance

When prompting an LLM to produce content under a **hard external limit** (tweet/toot, SMS, push notification, meta description, email subject), bake these into the prompt:

- **Demand a COMPLETE, self-contained thought.** "End with a finished sentence."
- **Ban the ellipsis explicitly.** "Do NOT trail off, do NOT use `...` or `…`, do NOT get cut mid-idea."
- **Set the target BELOW the platform cap** for headroom (e.g. ≤270 for a 300-char limit, leaving room for the link + safety).
- **Make mandatory elements non-negotiable.** "ALWAYS end with the link: <url>."
- **Give it an escape valve toward brevity:** "If the idea doesn't fit, say less — a shorter complete post beats a longer truncated one."

And make any **truncation backstop meaning-preserving** — cut at the last sentence/word boundary, never mid-word, never append a fabricated ellipsis:

```python
def trim_post(text, limit=290):  # backstop only; prompt aims <=270
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if cut > 40:
        return window[: cut + 1].rstrip()      # last full sentence
    sp = window.rfind(" ")
    return (window[:sp] if sp > 0 else window).rstrip()  # last whole word
```

## Why This Matters

A truncate-with-ellipsis backstop silently destroys meaning, and "≤N, be concise" alone reliably produces a post that maxes the budget and trails off — worst on a **public** account where a botty first impression costs followers. The fix is cheaper at the prompt than at the trim: tell the model to be *complete and shorter*, and keep the trim as a boundary-respecting safety net, not a meaning-shredder. Verified: post-fix dry-run produced a 242-char complete post ending in `https://wgmesh.dev` (PR #1841).

## When to Apply

Any LLM → fixed-length output where the platform truncates: social posts, SMS, push copy, SEO meta tags, email subject lines, chat-bubble previews. Especially when the output is published unattended or to a public surface.

## Related (same drip build, separate fixes)

- **OpenRouter `HTTP 000`** — the drip's LLM curl used `-m 60`; GLM-5.2 on a large prompt (full PR bodies + STRATEGY + FEATURE_MATRIX) exceeded it → curl timeout → `|| http="000"` → generation skipped. Fix: bump to `-m 180`, drop the needless `User-Agent: Mozilla` (OpenRouter isn't Cloudflare-gated; the working digest call has neither). PR #1840.
- **New `workflow_dispatch` workflow isn't dispatchable until it exists on the default branch** — `gh workflow run` 404s on a feature branch for a brand-new workflow. Merge to `main` first, then dry-run there (with `dry_run=true` to stay safe).
