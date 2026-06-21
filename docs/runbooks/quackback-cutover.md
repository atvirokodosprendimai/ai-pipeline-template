# Runbook — Quackback decision layer: provision, cut over, roll back

Operational companion to `docs/plans/2026-06-21-001-feat-quackback-decision-layer-plan.md`.
All facts below are sourced from the live QuackbackIO/quackback repo + quackback.io
docs (research 2026-06-21). Items marked **VERIFY** were not fully confirmed in docs and
must be checked against the running instance before the depending unit is proven.

---

## 0. Security posture (KTD9 — revised after grounding)

**Quackback API keys are all-or-nothing.** Every `qb_` key carries all seven scopes
(`read/write:feedback`, `read/write:changelog`, `read/write:help-center`,
`read/write:chat`). A key with `write:feedback` can call `triage_post` and set **any**
status — including `Accepted for Build` and `Rejected`.

> *"API keys get all seven scopes. OAuth tokens get only the scopes the user approved."*
> — quackback.io/docs/mcp

Consequence: the plan's KTD9 (server-enforced prohibition on the bot setting decision
statuses) **is not achievable**. Decision-status authority is enforced **client-side
only** — the adapter allowlist (`forge/quackback_status.py`, box-settable =
{Building, Ready for Review, Shipped}) plus the fact that box code never targets a
decision status.

**Accepted risk (operator decision 2026-06-21): the board is used only by trusted
cofounders.** Under that threat model the residual exposure — a leaked or buggy bot key
forging a founder decision — is acceptable. The bot key's blast radius already includes
GitHub write. Mitigations that remain mandatory:

- Box code MUST never call `set_status` with a decision status; the adapter allowlist
  raises locally if it does (defense-in-depth; asserted by U2 conformance via a **local**
  raise — the non-2xx server assertion in the plan's U2 execution note is dropped as
  infeasible).
- Rotate `QUACKBACK_TOKEN` on cofounder personnel change or any suspected exposure.
- Keep the board private (internal cofounders only) — never public/community.

---

## 1. Provision a self-hosted Quackback instance

### 1.1 Deploy (production single-host stack)

```bash
git clone https://github.com/QuackbackIO/quackback.git && cd quackback
cp .env.prod.example .env        # fill EVERY value — stack refuses to start half-configured
docker compose -f docker-compose.prod.yml up -d
```

Migrations run automatically on app startup. Upgrade later with:

```bash
git pull && docker compose -f docker-compose.prod.yml pull \
  && docker compose -f docker-compose.prod.yml up -d
```

Services in the prod stack:

| Service | Image | Notes |
|---|---|---|
| app | `ghcr.io/quackbackio/quackback:latest` | only host-published port (`${APP_PORT:-3000}:3000`); health `GET /api/health` |
| postgres | custom build (`docker/postgres/Dockerfile`) | requires `pg_cron`; **VERIFY** base PG version before pinning upgrades |
| dragonfly | `dragonflydb/dragonfly:v1.27.1` | Redis-compatible; BullMQ queue backend |
| minio + minio-init | `minio/minio`, `minio/mc` | optional S3 store (changelog image uploads); omit if unused |

Required env (`.env.example`):

```
DATABASE_URL=postgresql://postgres:password@host:5432/quackback
BASE_URL=https://feedback.<your-domain>
PORT=3000
SECRET_KEY=<>=32 chars>     # openssl rand -base64 32
REDIS_URL=redis://dragonfly:6379
```

> **Gotcha (`.env.example`):** do NOT wrap values in quotes and do NOT put inline comments
> on a value line — Docker `--env-file` reads everything after `=` literally. A quoted
> `DATABASE_URL="postgresql://..."` fails with `ERR_INVALID_URL`.

> Railway: no `railway.json` in the repo — there is no one-click template. Deploy on
> Railway by wiring `docker-compose.prod.yml` to Railway-managed Postgres + a
> Redis-compatible service manually.

### 1.2 First-run admin setup

Open `BASE_URL` → setup wizard: create the admin account, set the workspace name, create
the first board (the internal decision board). If you seeded demo data (`bun run db:seed`),
login is `demo@example.com` / `password` — do not seed a production instance.

### 1.3 Create the decision statuses

Create these eight statuses (Admin UI, or `POST /api/v1/statuses`). Category drives
roadmap/closed semantics:

| Status | slug | category |
|---|---|---|
| Open for Vote | `open_for_vote` | active |
| Needs Refinement | `needs_refinement` | active |
| Accepted for Build | `accepted_for_build` | active |
| Building | `building` | active |
| Ready for Review | `ready_for_review` | active |
| Rejected | `rejected` | closed |
| Cancelled | `cancelled` | closed |
| Shipped | `shipped` | complete |

API shape (confirmed): `POST /api/v1/statuses` `{name, slug, color, category, position,
showOnRoadmap, isDefault}`. Record each returned `statusId` (TypeID) — the adapter maps
slug→statusId for `set_status`.

### 1.4 Mint the bot key

Admin → Settings → Developers → create a named key (e.g. `autobox`). Shown **once** —
copy immediately. Format `qb_…`, all seven scopes (see §0).

### 1.5 Wire secrets to the box / CI

```bash
gh secret set QUACKBACK_URL   --body "https://feedback.<your-domain>"   # == BASE_URL
gh secret set QUACKBACK_TOKEN --body "qb_…"
```

Then propagate to the box env via the provision/`set-box-env` path (same mechanism as
prior `*_LIVE` flags). The pipeline reads `QUACKBACK_URL` / `QUACKBACK_TOKEN`; selecting
`forge_kind=quackback` with either unset fails loudly at config construction (U1).

---

## 2. API facts the adapter depends on

Base: `<BASE_URL>/api/v1`, `Authorization: Bearer qb_…`.

| Need | Fact | Source / status |
|---|---|---|
| Create Build Suggestion | `POST /api/v1/posts` | CONFIRMED |
| Read one post (drift re-read, confirm) | `GET /api/v1/posts/{postId}` | CONFIRMED |
| List accepted posts (ingest) | `GET /api/v1/posts?status=accepted_for_build&sort=newest&cursor=&limit=` | CONFIRMED; cursor pagination, `limit` max 100 |
| Set status (Building/Ready/Shipped) | `PATCH /api/v1/posts/{postId}` | **VERIFY** full schema against instance — REST path is in the API index; MCP `triage_post` is the documented equivalent |
| Comment | REST `POST /api/v1/posts/{postId}/comments` | **VERIFY** — MCP `comment_on_post` confirmed; REST schema not in fetched docs |
| Post id | string TypeID `post_01h…` — **not numeric** | CONFIRMED → U4 maintains `quackback_post_id`↔int map (KTD6/OQ3 fallback) |
| Idempotency / concurrency | only `updatedAt` (ISO 8601); **no** `status_version`/revision | CONFIRMED → KTD6 accept-transition timestamp fallback (OQ2 resolved) |
| Post metadata | no custom-fields API | CONFIRMED → encode via tags + body |

Webhooks (deferred unit, when a public receiver exists): HMAC-SHA256 over
`{timestamp}.{body}`, header **`X-Quackback-Signature`** (NOT `-256` as the plan guessed),
timestamp header `X-Quackback-Timestamp`, consumer enforces ≤5-min replay window. Secret
rotation `POST /api/v1/webhooks/{id}/rotate`.

---

## 3. Cutover (U9 — fill at cutover time)

Prerequisite: Phase 1–3 + U12 green in shadow against this real instance.

1. Drain in-flight GitHub issues on the old path (finish-clean).
2. Flip default `forge_kind=quackback` (config default or box env).
3. `gh issue create` path stays **flag-guarded, not deleted** — rollback is a config flip.
4. Verify: post-cutover observation run creates a Quackback post and **zero** GitHub
   issues; one end-to-end accept→build→merge→Shipped cycle completes.

## 4. Rollback (true config flip)

Set `forge_kind=github` → the still-present `gh issue create` path reactivates. If the
GitHub backlog was drained at cutover, reseed it. No code revert required.

---

## 5. Open / VERIFY before depending units are proven

- **VERIFY** `PATCH /api/v1/posts/{postId}` status-set request/response schema (U2/U3/U6).
- **VERIFY** REST comment endpoint shape (U2/U5) — else route comments via MCP later.
- **VERIFY** Postgres base version in `docker/postgres/Dockerfile` before pinning upgrades.
- Probe a live post payload to confirm the `updatedAt` field name used for the
  accept-transition idempotency marker (U2).
