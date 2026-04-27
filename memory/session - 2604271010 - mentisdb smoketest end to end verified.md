---
tldr: Provisioned org with MentisDB connection secrets and shipped a smoketest workflow — verified end-to-end agent memory write+read in 1.0s
session_start: 2026-04-27 09:58 UTC (continuation after first /eidos:done)
session_end: 2026-04-27 10:10 UTC
duration: ~12 minutes
---

# Session: MentisDB org provisioning + smoketest verification

## What got built (since last session)

- **Org secrets shipped** (visibility selected → `ai-pipeline-template`, `wgmesh`):
  - `MENTISDB_URL` = `https://mem.beerpub.dev`
  - `MENTISDB_USER` = `mentisdb`
  - `MENTISDB_PASSWORD` = (47-char alnum)
- **Smoketest workflow** at `.github/workflows/mentisdb-smoketest.yml`
  - workflow_dispatch + daily 04:17 UTC cron (after certbot renewal at 03:17)
  - Round-trip: POST `/v1/thoughts` (Finding type, unique marker per run) → POST `/v1/search` (text=marker) → assert marker in response
  - 5min job timeout, fail-fast on any HTTP error
- **First verified end-to-end agent memory call** — 1.0s round-trip:
  - Append returned full thought obj (id `243da501-0270-42f4-a896-f6d5247e635e`, hash chain intact, schema_version 3)
  - Search returned the same thought via marker text query

## API canonical learnings (verified from upstream src/)

29 ThoughtType enum values discovered via `src/lib.rs` lines 8585-8613. `Observation` is NOT one of them despite being used loosely in agent docs callouts. Use `Finding` for concrete observations.

POST `/v1/thoughts` shape (from `src/server.rs::AppendThoughtRequest`): required `thought_type` + `content`; many optional fields. Server returns `{thought: {...}, head_hash: "..."}`.

POST `/v1/search` shape: `chain_key`, `text`, `limit`, `thought_types[]`, `tags_any[]`, `since`/`until`, etc. Returns `{thoughts: [...]}`.

Full REST route inventory + ThoughtType + ThoughtRole catalog now in `reference_mentisdb_facts.md`.

## PR shipped this session

- #593 `feat: mentisdb smoketest workflow — round-trip append + search`

## State at session end

- 11 PRs total since initial scaffold (#579 → #593)
- Live deploy verified: `https://mem.beerpub.dev` auth-protected, smoketest passing
- Daily smoketest will catch regressions
- 24h follow-up agent (`trig_01WuwnhBaL5tCo4E5Y9QukMu`) still scheduled for 2026-04-27T23:33Z to re-check PR + health

## Memory updates

- Extended `reference_mentisdb_facts.md` with full REST API canonical reference
- Updated `reference_mentisdb_hetzner_deploy.md` PR chain with #593

## What's next (deferred)

Same as last session export, all still open:
- Pipeline module first-apply needs `terraform import` for 4 pre-existing resources
- mentisdb skill registry doesn't enforce Ed25519 signing by default
- Public dashboard (port 9475) only via SSH tunnel
- Rotate the password leaked in conversation history
- Consume MentisDB from a wgmesh workflow (smoketest only validates from ai-pipeline-template — should also dispatch from wgmesh to confirm cross-repo org-secret access works)
