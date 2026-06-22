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

Base: `<BASE_URL>/api/v1`, `Authorization: Bearer qb_…`. **All rows below VERIFIED against
the live instance `http://89.167.62.47:3000` on 2026-06-21** (status codes observed inline).

| Need | Fact | Status |
|---|---|---|
| Create Build Suggestion | `POST /api/v1/posts` `{boardId, title, content, statusId?}` → **201** | VERIFIED |
| Read one post (drift re-read, confirm) | `GET /api/v1/posts/{postId}` → **200** | VERIFIED |
| List accepted posts (ingest) | `GET /api/v1/posts?status=accepted_for_build&cursor=&limit=` → **200** | VERIFIED — filter is by status **SLUG** |
| **Filter gotcha** | `?status=<slug>` filters; **`?statusId=<id>` is IGNORED** (returns all) | VERIFIED — ingest MUST use the slug param |
| Set status (Building/Ready/Shipped) | `PATCH /api/v1/posts/{postId}` `{"statusId":"<status TypeID>"}` → **200** | VERIFIED — body takes the status **id**, not slug; box maps slug→id via `GET /statuses` |
| Comment | `POST /api/v1/posts/{postId}/comments` `{"content":"…"}` → **201** | VERIFIED |
| Delete (probe cleanup) | `DELETE /api/v1/posts/{postId}` → **204** | VERIFIED |
| Post id | string TypeID `post_01h…` — **not numeric** | VERIFIED → U4 maintains `quackback_post_id`↔int map (KTD6/OQ3) |
| Idempotency / concurrency | post payload has **no** `version`/`revision`/`statusVersion`; only `createdAt`/`updatedAt` | VERIFIED → KTD6 accept-transition `updatedAt` marker (OQ2 resolved) |
| `decided_by` (KTD10, PII-safe) | use `ownerPrincipalId` (opaque) — payload also exposes `authorEmail`/`authorName`; **never persist those** | VERIFIED |
| Status object | `{id (status_…), name, slug, color, category(active\|complete\|closed), position, showOnRoadmap, isDefault}` | VERIFIED |
| Post metadata | no custom-fields API | CONFIRMED → encode via tags + body |

**Live instance state (2026-06-21):** workspace `wgmesh`; board **Build Suggestions**
`board_01kvm80e4df69b5wf8t1v6x6xh` (slug `build-suggestions`); the 8 decision statuses
created (slugs `open_for_vote`/`needs_refinement`/`accepted_for_build`/`building`/
`ready_for_review`/`rejected`/`cancelled`/`shipped`); bot key `autobox` minted;
`QUACKBACK_URL`/`QUACKBACK_TOKEN` set as repo secrets. (6 default statuses + 3 default
boards from onboarding also present — harmless; the box targets `build-suggestions`.)

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

## 5. VERIFY items — RESOLVED 2026-06-21 (probed against the live instance)

- ✅ `PATCH /api/v1/posts/{postId}` `{"statusId":"<id>"}` → 200 (set-status; body takes id).
- ✅ `POST /api/v1/posts/{postId}/comments` `{"content":"…"}` → 201.
- ✅ Idempotency marker = `updatedAt` (no version/revision field on the post payload).
- ✅ Ingest filter = `?status=<slug>` (the `?statusId=` param is ignored — see §2).
- Still open: Postgres base version in `docker/postgres/Dockerfile` before pinning upgrades
  (not blocking — the stack runs on the built image).

---

## 6. Internal roadmap (configured 2026-06-22)

The internal roadmap is a view of board posts grouped by status where the status carries
`showOnRoadmap = true`. The box already drives posts through statuses (`_mirror_quackback`),
so the roadmap auto-populates — the only config is the per-status flag.

**Decision (`docs/brainstorms/2026-06-22-quackback-roadmap-changelog-requirements.md`):** show
only the **box lane** — Accepted for Build, Building, Ready for Review, Shipped. Backlog
(Open for Vote, Needs Refinement), terminal-negative (Rejected, Cancelled), and the 6 unused
Quackback default statuses (open, under_review, planned, in_progress, complete, closed) are
**off**.

**API (VERIFIED 2026-06-22):** `PATCH /api/v1/statuses/{id}` `{"showOnRoadmap": <bool>}` → 200.
Applied with the `qb_` bot key — only the four box-lane statuses are `true`. To change the
roadmap, flip the flag on the relevant status id (`GET /api/v1/statuses` for ids).

> The changelog half of that brainstorm (daily roll-up → Quackback changelog, retire the
> Unsend email) is NOT built — it needs the create-changelog endpoint VERIFIED first.
