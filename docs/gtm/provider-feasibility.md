# GTM rent-a-human provider — feasibility decision note (U1)

**Plan:** `docs/plans/2026-06-25-001-feat-gtm-rent-a-human-executor-plan.md` (U1)
**Date:** 2026-06-25
**Status:** research-confirmed; live-probe + funding pending a cofounder action (see Gate 4)

This note is the U1 spike deliverable: name a rented-human provider that clears the
four gates, state its spend-reporting model, and map its result/proof shape onto the
U2 adapter contract. The lane build (U2+) targets the **adapter**, so the specific
provider can be swapped behind the seam; this note picks the default to wire in.

---

## The four gates

| # | Gate | How confirmed |
|---|------|---------------|
| 1 | Unattended API dispatch (create task + retrieve result, no human account manager) | Research / vendor docs |
| 2 | Structured completion proof (machine-readable result + evidence) | Research / vendor docs |
| 3 | EU/GDPR data-handling posture (Article 28 DPA) — jobs may touch EU contacts | Research / vendor docs |
| 4 | Acceptable per-task cost **on a funded account** | **Cofounder action** — signup + DPA + funding |

Gates 1–3 are confirmable from documentation and prior art. **Gate 4 (a funded,
EU-DPA account) is a capital decision the pipeline cannot self-serve** — it needs a
cofounder to sign up, accept the DPA, and fund the account. The lane build proceeds
against a fake provider (U2) without it; only the live cutover (real dispatch) waits
on Gate 4.

---

## Recommendation: Toloka (primary)

| Candidate | Gate 1 API | Gate 2 proof | Gate 3 EU/GDPR | ~cost/task | Verdict |
|-----------|-----------|--------------|----------------|------------|---------|
| **Toloka** | Full REST + Python SDK (`toloka-kit`) | Structured JSON per assignment + built-in QC (majority vote, honeypots, skill scoring) | GDPR + ISO 27701, Article 28 DPA | $0.10–0.50 | **Primary** |
| Microworkers | REST API v2 (campaigns) | Result + configurable screenshot proof URLs | EU domicile (Slovenia); DPA less explicit | $0.10–0.50 | Alt — GTM task types (signups/recon) |
| HumanOps | REST + **MCP server** | Photo/structured proof before payment settles | **Unverified** | Undisclosed | Watch — best architectural fit; verify pricing + GDPR |
| MTurk | Best-documented REST API | Structured fields | **US data posture, no DPA** | $0.20–0.60 | **Reject for EU contact data** |
| Prolific | Full REST API | Completion codes + JSON | GDPR, EU-safe | $12+/hr | Reject — task types prohibit signups/list-building |
| Upwork / Fiverr | Partner-gated / none | None | — | — | Reject — no autonomous dispatch |

**Why Toloka:** only candidate clearing Gates 1–3 cleanly — a real EU Article 28 DPA
(ISO 27701), a full programmatic API + SDK, built-in quality control that lowers our
verification burden, and a low per-task cost. Microworkers is the fallback for
account-creation/signup tasks where Toloka's worker pool skews research-oriented.
HumanOps is worth a direct evaluation (MCP-native → near-zero client code) once its
pricing and GDPR posture are verified.

Prior art: a documented 2025 build dispatched ~300 tasks via MTurk/Toloka/Microworkers
at ~$0.30/task with programmatic result validation and no human in the loop — the
dispatch-and-verify loop is proven at small scale.

---

## Spend-reporting model

Provider spend is reported **asynchronously** (rewards settle after worker submission /
approval, not synchronously at dispatch). A synchronous per-job dollar cap is therefore
**not implementable**. The budget gate (U6) must be a **pre-dispatch reservation against
a tracked envelope + a bounded-attempts ceiling**, reconciling actual cost on close —
never a hoped-for synchronous post-hoc figure. (Confirms the plan KTD and the
multi-model-routing learning.)

---

## Adapter-contract requirements (input to U2)

The U2 vendor-agnostic protocol must express, provider-independently:

- **`dispatch(job_spec) -> handle`** — submit one task; return an opaque provider handle
  (Toloka: pool/task id). Idempotency key on the job so a retry does not double-dispatch.
- **`fetch_result(handle) -> result`** — poll/retrieve. `result` distinguishes four
  states explicitly (no coercion to "done"): `completed` (with structured payload +
  proof), `empty`, `garbage/invalid`, `pending`.
- **Result shape:** `{ payload, proof, worker_meta, cost_estimate? }` where `proof` is a
  structured artifact (Toloka assignment JSON / Microworkers screenshot URL / HumanOps
  photo) the U5 verifier checks against the dispatched job.
- **Credentials:** provider keys reach the adapter via an **allowlist** env (not
  denylist), re-added only for the routed provider — fail-closed on a missing key.
- **External-call hygiene:** explicit non-default `User-Agent` on provider HTTP calls
  (Cloudflare-fronted APIs 403 default `urllib` UAs); stamp any cached endpoint/ID
  reference with `last_verified` and re-discover via the API at dispatch time rather than
  trusting baked config.

---

## Open cofounder action (Gate 4 — blocks live cutover, not the build)

1. Sign up for Toloka (requester), accept the Article 28 DPA, fund the account.
2. Set the **spend envelope** amount + refresh cadence (U6 config input).
3. Provide the API credential to the pipeline's vault/allowlist env.

Until then: build and test the full lane against the fake provider (U2–U9); the live
provider swap + first real dispatch is the only step that waits.
