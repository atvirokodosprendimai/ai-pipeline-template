# Wire Quackback roadmap + changelog (internal ops hub)

**Date:** 2026-06-22 · **Scope:** Standard · **Status:** ready for `/ce-plan`
**Origin:** operator — "wire roadmap, changelog to quackboard as well" (Quackback decision-layer follow-on)
**Grounding:** `/tmp/compound-engineering/ce-brainstorm/qb-roadmap-changelog/grounding.md`

## Outcome

Consolidate the founding team's internal ops comms into the single private Quackback
instance (`http://89.167.62.47:3000`): the board already holds **decisions**, this adds a
**roadmap** (track committed→shipped work) and a **changelog** (the daily ship-log), so the
team has one private hub instead of the board plus a scattered email digest.

**Audience is internal only** — the board and the whole portal stay private (cofounders),
exactly as the decision-layer locked (KTD9: "never public/community"). Nothing here exposes
a public-facing roadmap or changelog.

## What we're building

### 1. Changelog — the daily ship-log moves to Quackback (replaces the email digest)
- The existing `daily-release-notes.yml` already gathers the day's merged PRs (cross-repo),
  groups them into themes via an LLM, and emails a formatted digest via Unsend.
- **Change:** keep the gather + LLM roll-up; **POST the result as one daily Quackback
  changelog entry** instead of emailing it. The changelog entry is now the home of the
  ship-log.
- **Retire the email fully** — no Unsend send. (Accepted risk: no daily push; the team reads
  the changelog in the portal. Same silent-stall shape as the bare cutover (KTD3) — revisit
  if the team misses the push; a thin link-email is the obvious follow-up.)
- Feed = **all merged PRs, one daily entry** (not per-Shipped-post) — full coverage including
  routine/housekeeping work, matching what the digest captures today.
- The roll-up text passes the existing sanitise wall before the POST (public-repo discipline,
  even though the instance is private).

### 2. Roadmap — internal status view of the box lane — ✅ DONE 2026-06-22
> Applied live: `showOnRoadmap` set `true` on the 4 box-lane statuses, `false` on all others
> (backlog + negatives + 6 unused defaults) via `PATCH /api/v1/statuses/{id}`. Documented in
> `docs/runbooks/quackback-cutover.md` §6. Near-zero box code as predicted.

- Quackback renders a roadmap from posts grouped by status where the status carries
  `showOnRoadmap = true`. The box already drives posts through statuses
  (`_mirror_quackback`: Building → Ready for Review → Shipped).
- **Change:** enable `showOnRoadmap` on the **box-lane statuses** — Accepted for Build,
  Building, Ready for Review, Shipped — so the roadmap shows committed → in-flight → done.
  Undecided backlog (Open for Vote, Needs Refinement) and terminal-negative (Rejected,
  Cancelled) stay **off** the roadmap.
- Near-zero box code: the roadmap auto-populates as the box mirrors status; the only work is
  setting the `showOnRoadmap` flag on four statuses (see Open Questions for the mechanism).

## Scope boundaries

**In:** daily roll-up → Quackback changelog (new `QuackbackClient.create_changelog`); retire
the Unsend email; `showOnRoadmap` on the four box-lane statuses; sanitise wall on the
changelog body.

**Explicitly out:**
- **Public/community surfaces** — board and portal stay private/internal.
- **Per-Shipped-post changelog entries** — chose the daily roll-up of all PRs instead.
- **Backlog/negative statuses on the roadmap** — only the box lane shows.
- **Box-native migration of the digest** — the roll-up stays in `daily-release-notes.yml`
  (Actions cron) for now. *Tension noted:* this sits against the actions=CI/CD-only retarget
  (`project_actions_cicd_only_retarget`); moving the roll-up onto the box control loop is a
  later, larger move, deferred deliberately.
- **Comment / two-way steering** — unrelated (U10/U11), out.

## Success criteria

- A daily run posts one changelog entry to the Quackback instance containing the themed
  merged-PR roll-up; no email is sent.
- The internal roadmap shows posts under Accepted for Build / Building / Ready for Review /
  Shipped, and shows nothing under Open for Vote / Needs Refinement / Rejected / Cancelled.
- A post the box drives to Shipped appears under Shipped on the roadmap with no manual step.
- The changelog body passes the sanitise wall (a roll-up that fails is blocked/degraded, not
  posted raw).

## Open questions (for planning)

- **Changelog API shape — VERIFY first.** `QuackbackClient` has no changelog method and the
  POST endpoint/payload is unconfirmed (the `write:changelog` scope exists; minio is noted as
  optional changelog image storage). Probe the live instance for the create-changelog
  endpoint + body shape before implementing, mirroring the cutover's VERIFY discipline
  (`docs/runbooks/quackback-cutover.md` §2). If a changelog needs a category/release grouping
  or a publish-vs-draft state, resolve it against the real API.
- **Roadmap config mechanism.** One-time manual set of `showOnRoadmap` (UI or `PATCH
  /statuses`, documented in the runbook, zero code) vs the box ensuring it idempotently at
  startup (drift-proof across a reprovision, small code). Lean: one-time runbook step; add a
  box ensure-step only if the flag drifts.
- **Changelog cadence/empty days.** Does an all-housekeeping day still warrant an entry, or
  skip when nothing notable merged? (The current digest always emails.)

## Dependencies / assumptions

- The Quackback instance is live and the box holds a working `qb_` key (post-cutover: yes).
- The bot key carries `write:changelog` (all-scopes key — yes).
- `daily-release-notes.yml` keeps working as the gather + LLM-theming source; only its sink
  changes (email → changelog POST).
- **Assumption (unverified):** Quackback exposes a REST create-changelog endpoint usable with
  the `qb_` Bearer key — must be confirmed (see Open Questions) before the changelog unit is
  built; the roadmap half does not depend on it.

## Approach

**Extend, not net-new.** Reuse `daily-release-notes.yml` (gather + roll-up) and
`QuackbackClient`; add one client method (`create_changelog`) and swap the email sink for a
changelog POST; set `showOnRoadmap` on four statuses. The two halves are independent — the
roadmap (config) can ship without the changelog (needs the API VERIFY), so they can sequence
separately.
