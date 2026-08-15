---
title: "Cloudflare error 1010 / 403 blocks default urllib User-Agent; set an explicit UA"
category: integration-issues
date: 2026-06-25
tags: [cloudflare, user-agent, urllib, http-403, error-1010, external-api, bot-block, gtm]
---

# Cloudflare error 1010 / 403 blocks default urllib User-Agent

## Problem

Calling a Cloudflare-fronted API with Python's default `urllib` User-Agent returns
HTTP 403 with "error code 1010" — CF blocks the known bot UA. `curl` to the same
endpoint works, which masks the cause. Any external provider API (Toloka,
Microworkers, HumanOps, etc.) the GTM lane calls may sit behind Cloudflare.

## Root Cause

Cloudflare bot-management fingerprints and blocks default library User-Agents
(`Python-urllib/x.y`). The request never reaches the origin; the 403 is from CF.

## Fix / Prevention

- Set an **explicit, non-default `User-Agent`** header on every external provider
  HTTP call (a real browser-like or named-app UA).
- Prefer a maintained HTTP client (`requests`/`httpx`) which is less likely to use
  the flagged default, but still set an explicit UA.
- When an external call 403s but `curl` works, suspect UA/CF before auth.
- Stamp cached endpoint/IDs with `last_verified` and re-discover via the API at
  call time (the stale-config / silent-rot lesson).

## Related

- Provider adapter external-call hygiene: `pipeline/wgmesh_pipeline/gtm_lane/provider.py`
- `docs/solutions/integration-issues/polar-checkout-404s-from-stale-config-2026-05-08.md`
