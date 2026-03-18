---
title: "Phantom infrastructure outages caused by wrong URLs in health.json"
category: integration-issues
date: 2026-03-18
tags: [health-check, observation-loop, infrastructure, dns, cloudflare, coroot]
---

## Problem

The observation loop reported coroot (530), tvcentras (connection error), and creu (connection error) as down for multiple days. The loop created `needs-human` issues (#455) and flagged infra outages as top-priority actions. VPS diagnostics showed all containers healthy and running.

## Root Cause

`company/health.json` contained wrong URLs for the services:

- `coroot.beerpub.dev` — not a configured Caddy route; Cloudflare returns 530. Actual URL: `table.beerpub.dev`
- `tvcentras.lt` — domain DNS doesn't point to the VPS. Actual URL: `tv.beerpub.dev`
- `creu.lt` — genuinely defunct/unreachable domain, removed from monitoring

The observation loop and health check workflows trusted these URLs without validation. Every daily assessment reported phantom outages, creating noise and wasting human attention on non-issues.

## Solution

1. Fixed `health.json` URLs to match actual service endpoints
2. Removed defunct `creu.lt` endpoint
3. Also created `restart-services.yml` workflow in coroot-cicd during investigation (useful for future real outages)
4. Recreated coroot containers via the new workflow (unnecessary, but confirmed services were healthy)

```json
{
  "endpoints": [
    {"name": "chimney", "url": "https://chimney.beerpub.dev"},
    {"name": "cloudroof", "url": "https://cloudroof.eu"},
    {"name": "coroot", "url": "https://table.beerpub.dev"},
    {"name": "tvcentras", "url": "https://tv.beerpub.dev"}
  ]
}
```

## Prevention

- When `init.sh` seeds health endpoints, validate each URL returns HTTP 2xx before committing. A simple `curl -sf` check during setup would catch wrong URLs immediately instead of letting them poison daily assessments for days.
