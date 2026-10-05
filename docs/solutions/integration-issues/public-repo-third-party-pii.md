---
title: "Don't commit third-party PII to a public repo; GitGuardian is alert-only"
category: integration-issues
date: 2026-06-25
tags: [pii, public-repo, privacy, gdpr, gitguardian, outreach, stargazer, sanitise, gtm]
---

# Don't commit third-party PII to a public repo; GitGuardian is alert-only

## Problem

This is a **public** repo. Committing real third-party emails or contact data
(e.g. scraped stargazer emails) leaks PII and risks GDPR exposure. GitHub/
GitGuardian secret scanning is **alert-only** — it warns after the fact, it does
not block the commit. The GTM lane, which builds lead lists and may handle EU
contacts, makes this a first-class concern.

## Root Cause

No commit-time gate stops PII. Relying on a post-hoc scanner means the data is
already public by the time the alert fires; git history keeps it even after a
"delete".

## Fix / Prevention

- **List-building collects public signals only** — handle, public profile link,
  and the public signal (starred/forked/commented). Never scraped private emails.
- Route real contact data through the **sanitise wall** (`company/scripts/sanitise.sh`)
  in both directions; it warns on email patterns and fails-closed on secrets.
- Treat any rented-human job that would collect PII as **needs-human / high-risk**,
  not a low-risk auto-dispatch.
- Provider handling EU data must have an Article 28 DPA (the cloudroof/GTM provider
  gate — see `docs/gtm/provider-feasibility.md`).

## Related

- `docs/solutions/gtm-playbook/core-four-warm-outreach.md` (public-signal list-building)
- GTM rent-a-human lane plan: `docs/plans/2026-06-25-001-feat-gtm-rent-a-human-executor-plan.md`
