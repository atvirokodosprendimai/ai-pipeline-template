# Specification: Issue #1589

## Classification
feature

## Deliverables
both

## Problem Analysis

The paid-customer metric is currently sourced from an HTML scrape of `chimney.beerpub.dev` inside `strategy-audit.yml` (the step named "Fetch paid customers from chimney"). This scrape is brittle: it depends on a specific DOM shape, can return `null` on any fetch failure, and passes a silent `null` forward rather than surfacing an error. `company/metrics.json` has been stale since April; every pulse report carries "0 customers" forward unverified.

A prior Polar org/slug mismatch (`atvirokodosprendimai` instead of the real org `it-uoga-mb`) caused a 19-day revenue-blindness incident where checkout 404'd while the loop logged "0 subs". The fix is authoritative measurement: a committed, fresh-or-`UNKNOWN` `company/funnel-state.json` artifact reconciled from the Polar API (`it-uoga-mb` org, `api.polar.sh`), with per-stage liveness checks, a daily sandbox synthetic transaction, and loud escalation on any breach.

**Phase A (U1–U7)** ships the core value in-repo: authoritative paid truth, freshness contract, liveness, synthetic heartbeat, escalation, and pulse/loop wiring. The top-of-funnel stages (visit, checkout-click) render `UNKNOWN` until Phase B (U8–U10) lands PostHog instrumentation, which depends on locating the cloudroof.eu site source outside this repo.

Key design decisions carried into this spec:
- Scheduled Polar-API pull (not an inbound webhook) keyed on `order.paid`, matching `checkout-monitor.yml`'s `13 */6` cadence.
- `company/funnel-state.json` is counts-only (no amounts, no PII, no raw payloads); single writer is the reconcile workflow.
- Past TTL → every consumer renders `UNKNOWN`, never a carried-forward prior value.
- `POLAR_TOKEN` → `api.polar.sh` only; `POLAR_SANDBOX_TOKEN` → `sandbox-api.polar.sh` only. Mismatch is a loud failure, not a silently wrong read.
- Breaches escalate to an idempotent `fn:billing` issue (label-keyed, `GITHUB_TOKEN` + `issues: write`); `needs-human` is reserved for non-contractable Polar-account actions.
- No `|| true` anywhere in detection or liveness paths.
- `source` values from Polar order metadata are allowlisted (`^[a-z0-9_-]{1,32}$`, else → `other`) before becoming JSON keys.
- The `material_fingerprint` includes `last_verified` so every successful reconcile lands a freshness heartbeat — the TTL can only lapse when reconcile actually fails or stops.

## Implementation Tasks

### Task 1: Polar reconcile script

- **File:** `company/scripts/polar-reconcile.sh` (create)
- **Where:** New file alongside other collector scripts
- **What:** Shell script that authenticates with `POLAR_TOKEN`, verifies it is pointed at `api.polar.sh` (exits non-zero with a clear error if the host does not match), resolves the `it-uoga-mb` org and the three cloudroof product UUIDs via the Polar API (fails loudly on mismatch — this resolution is a recurring liveness stage, not a startup-only check), counts distinct active subscriptions/customers across the three seed products as the paid-customer count (renewals and repeat orders must not inflate it), reads each order's `metadata.source` field, allowlists/normalizes it against `^[a-z0-9_-]{1,32}$` (anything else → `other`), and writes a structured result to stdout as JSON. A fetch failure yields `"status":"fetch_failed"` — never a `0`. No token, auth header, or raw order object is echoed; only count and status fields are emitted. Uses `curl -fsS` (silent, but fail-on-error and show-errors) so logs stay quiet while failures still surface — never a bare `-s` that swallows errors.
- **Detail:** The script is the authoritative paid-count source; it must not swallow API errors with `|| true`. On API error the script exits non-zero and outputs `{"status":"fetch_failed","paid_count":null}`. On org/product UUID mismatch it exits non-zero with a clear message. On success it outputs `{"status":"ok","paid_count":<n>,"source_breakdown":{...}}`. Follows the Polar-API call shape in `checkout-monitor.yml` (resolve product IDs → query orders/subscriptions). The three cloudroof product UUIDs are enumerated dynamically from the API by org+tag (not hardcoded), so a UUID rotation does not silently break the count.

### Task 2: Polar reconcile unit tests

- **File:** `company/scripts/test-polar-reconcile.sh` (create)
- **Where:** New file alongside other `test-*.sh` harnesses
- **What:** Bash test harness that mocks `curl` to cover: (a) orders present → correct paid count and source breakdown; (b) API error → `fetch_failed` status emitted, non-zero exit, no `0` count; (c) empty result → `0` count with `ok` status (the script emits status `ok`/`fetch_failed`; the `live`/`stale`/`unknown` stage *health* is assigned later by the workflow, not the script); (d) wrong org/product UUID → loud failure; (e) token pointed at sandbox host → loud failure; (f) malformed or oversized `source` value → normalized to `other`, never written verbatim.
- **Detail:** Each scenario asserts the exit code and the JSON output field values. No live API calls — uses local mock fixtures. Follows the pattern in `company/scripts/test-collect-memory.sh`.

### Task 3: funnel-state.json seed file

- **File:** `company/funnel-state.json` (create)
- **Where:** New file in `company/`
- **What:** Seed artifact with all stages set to `unknown` health, `null` counts, `last_verified` set to `null` (so it reads as `UNKNOWN` until the first reconcile — matching the schema example below and the TTL reader's null handling), `run_count` 0, and an empty `material_fingerprint`. No amounts, no customer identity, no raw payloads.
- **Detail:** Schema: `{"schema_version":1,"run_count":0,"last_verified":null,"material_fingerprint":"","stages":{"paid":{"count":null,"health":"unknown","last_verified":null,"source_breakdown":{}},"visit":{"count":null,"health":"unknown","last_verified":null},"checkout_click":{"count":null,"health":"unknown","last_verified":null}},"liveness":{"paid_api":{"health":"unknown","last_checked":null},"prod_uuid_resolution":{"health":"unknown","last_checked":null}},"synthetic":{"health":"unknown","last_run":null,"sandbox_order_count":0}}`. The `paid` stage is the only one that will be `live` after Phase A; `visit` and `checkout_click` render `UNKNOWN` until Phase B.

### Task 4: Freshness/TTL reader

- **File:** `company/scripts/funnel-read.sh` (create)
- **Where:** New file alongside other collector scripts
- **What:** Given the artifact path and an optional TTL override (default 86400 seconds / 24 h for `paid`, configurable), reads each stage's `last_verified` and current time, and prints `UNKNOWN` for any stage whose `last_verified` is null or older than the TTL. Outputs a flat key=value block (e.g. `PAID_CUSTOMERS=UNKNOWN`) consumable by GitHub Actions `>> $GITHUB_ENV`.
- **Detail:** Single source of the freshness rule so pulse and loop cannot diverge. Never returns a stale numeric value as current. If the artifact does not exist, every stage emits `UNKNOWN`. The reader does not modify the artifact. Uses only `jq`, `date`, and `bash` builtins — no external deps.

### Task 5: Freshness/TTL reader unit tests

- **File:** `company/scripts/test-funnel-read.sh` (create)
- **Where:** New file alongside other `test-*.sh` harnesses
- **What:** Covers: (a) fresh `last_verified` → numeric value returned; (b) `last_verified` older than TTL → `UNKNOWN`; (c) `last_verified` null → `UNKNOWN`; (d) stage missing entirely → `UNKNOWN`; (e) artifact file missing → all `UNKNOWN`.
- **Detail:** Uses synthetic JSON fixtures with backdated timestamps. Asserts exact output strings. No live API calls.

### Task 6: Liveness assertion script

- **File:** `company/scripts/funnel-liveness.sh` (create)
- **Where:** New file alongside other collector scripts
- **What:** Invoked by the reconcile workflow (not a standalone writer). Asserts: (1) Polar API `api.polar.sh` is reachable and returns a semantically valid response (not just a 2xx) — specifically that the `it-uoga-mb` org exists and the three cloudroof product UUIDs resolve to the expected product names; (2) `company/funnel-state.json` exists and has a non-empty `material_fingerprint` (the seed is an empty string, so "non-empty" proves reconcile has run at least once). On any assertion failure, opens or reuses an `fn:billing` GitHub issue (idempotent by label, using `GITHUB_TOKEN` + `issues: write`) and writes a breach signal to stdout for the workflow to mark the affected stage `UNKNOWN`. The issue body contains only: stage name, health value, `last_verified`, and the Actions run URL — never raw API responses, amounts, customer identity, or auth headers. Returns exit code 1 on breach so the calling workflow treats it as a step failure.
- **Detail:** Semantic content check is mandatory: a 302 to a marketing page passes a bare `curl -I` but is a breach here. Resolves the prod org+product to their expected UUIDs on every liveness run (not once at startup) — a slug regression is the documented 19-day blindness mode and must be caught here. No `|| true` around detection. Follows `checkout-monitor.yml` idempotent-issue pattern and `pipeline-health.yml` circuit-breaker/escalation shape.

### Task 7: Liveness unit tests

- **File:** `company/scripts/test-funnel-liveness.sh` (create)
- **Where:** New file alongside other `test-*.sh` harnesses
- **What:** Covers: (a) all assertions pass → exit 0, no issue opened; (b) Polar API unreachable → breach signal + `fn:billing` issue opened exactly once; (c) prod UUID mismatch (slug regression) → breach, not a silent `0`; (d) recovery after breach → stage returns to `live`, no duplicate issue; (e) issue body contains no amount, email, payload, or token field.
- **Detail:** Mocks `curl` and `gh` CLI. Asserts exit codes and stdout. Verifies idempotency by calling twice in breach state and checking `gh issue create` was invoked only once (uses an open-issue-by-label check before creating).

### Task 8: Synthetic sandbox transaction script

- **File:** `company/scripts/polar-synthetic-txn.sh` (create)
- **Where:** New file alongside other collector scripts
- **What:** Authenticates with `POLAR_SANDBOX_TOKEN` bound to `sandbox-api.polar.sh` (exits non-zero with a clear error if host mismatch). Creates a sandbox checkout with `metadata.source=synthetic-heartbeat`. Attempts headless completion with test card `4242 4242 4242 4242`; if the Polar sandbox API does not support headless card completion (the checkout requires a Stripe hosted-page confirm), emits a degraded heartbeat (`{"status":"degraded","reason":"headless-completion-unavailable","checkout_session_created":true,"reachable":true}`) rather than a false `order.paid`. On success asserts that `order.paid` was received. The script is side-effect-free — it does **not** write or assert `company/funnel-state.json`; the reconcile workflow (Task 10) owns the artifact write and the state-mutation assertion (single-writer). Sandbox order counts are tracked in the `synthetic` field only — never added to `stages.paid.count`. Returns a JSON result block to stdout for the reconcile workflow to write.
- **Detail:** Spike headless completion first (verify whether `sandbox-api.polar.sh` supports a programmatic card confirm endpoint). If automatable: full `order.paid` assertion. If not: degrade gracefully to checkout-session-created + reachability heartbeat and label it `degraded` in the state. A misconfig (wrong token, wrong host) → `fn:billing` escalation via the liveness script. Never echoes token, raw checkout object, or auth header to stdout/logs.

### Task 9: Synthetic transaction unit tests

- **File:** `company/scripts/test-polar-synthetic-txn.sh` (create)
- **Where:** New file alongside other `test-*.sh` harnesses
- **What:** Covers: (a) successful headless sandbox checkout → `order.paid` observed, synthetic stage `live`; (b) headless unavailable → degraded heartbeat recorded and flagged, not a false green; (c) misconfig (wrong token) → `fn:billing` escalation triggered; (d) sandbox order count never appears in prod paid count.
- **Detail:** Mocks `curl` and `gh`. Asserts JSON output fields. Verifies sandbox count isolation from `stages.paid.count`.

### Task 10: Reconcile cron workflow

- **File:** `.github/workflows/funnel-reconcile.yml` (create)
- **Where:** New file alongside other cron workflows
- **What:** Cron workflow (`13 */6 * * *`, matching `checkout-monitor.yml`) that is the sole committer of `company/funnel-state.json`. Sequential steps: (1) run `polar-reconcile.sh` (U1) to fetch paid data; (2) run `funnel-liveness.sh` (U4) to assert liveness and receive breach flags; (3) run `polar-synthetic-txn.sh` daily (U5) — triggered by `github.event.schedule` date; (4) assemble all stage counts, health flags, and a new `material_fingerprint` that includes `last_verified`; (5) run a pre-commit guard that scans the rendered artifact for disallowed fields (amounts, currency symbols, email patterns, customer identity, checkout URLs, raw payload keys) and aborts the commit if any are present; (6) commit via branch + PR and merge via the heartbeat fast-lane. A state-mutation assertion step verifies the artifact actually changed after a successful reconcile run (fails the workflow if a claimed-successful run did not update state). Does not depend on the commit to trigger any downstream workflow.
- **Detail:** Permissions: `contents: write`, `issues: write`, `pull-requests: write`. Uses `PUSH_TOKEN` for commits. The `material_fingerprint` is `sha256` of the content excluding `run_count` and `last_run` fields (so a content-identical run is still distinguishable from a no-data run by its `last_verified` — every reconcile always commits a freshness heartbeat). `bash -n` and `shellcheck` clean.

### Task 11: Update heartbeat-pr-automerge fast-lane

- **File:** `.github/workflows/heartbeat-pr-automerge.yml` (modify)
- **Where:** All three gates the `validate-and-merge` job applies, not just the job-level `if:` — the title→expected-branch pattern map, the expected-branch check, and the changed-file allowlist.
- **What:** Add the funnel reconcile PR title prefix (`chore: funnel-state update`) to the title→branch pattern map, the funnel reconcile branch prefix to the expected-branch check, and `company/funnel-state.json` to the changed-file allowlist. All three are required — updating only the job-level `if:` leaves the PR ineligible — so the state PR actually auto-merges to `main` under the existing sanitise guards.
- **Detail:** Without this addition, the state PR sits unmerged and `last_verified` on `main` never refreshes, defeating the TTL freshness contract. Follow the same pattern as the existing `chore: supervisor-rank state` entry.

### Task 12: Replace chimney scrape in strategy-audit.yml

- **File:** `.github/workflows/strategy-audit.yml` (modify)
- **Where:** Replace the step named "Fetch paid customers from chimney" and its companion `PAID_CUSTOMERS` env usage
- **What:** Remove the chimney HTML scrape step. Replace it with a step that calls `bash company/scripts/funnel-read.sh company/funnel-state.json` and sources its output into the environment. If the reader emits `PAID_CUSTOMERS=UNKNOWN`, the pulse report renders `UNKNOWN` (not `null` or `0`). Update the metric_row call and the `current_metrics` JSON assembly to treat `UNKNOWN` as a string sentinel rather than a numeric null.
- **Detail:** The chimney URL and HTML-parsing logic are fully removed. The `CHIMNEY_URL` env var is no longer needed. The `PAID_FETCH_STATUS` field in `current_metrics` maps to `funnel_read` (not `chimney`). The `observation-loop.yml` already polls Polar live for MRR; the artifact is authoritative for the *count* only, and any divergence between artifact count and live read is surfaced (never silently picked).

### Task 13: Update pulse metric source config

- **File:** `.compound-engineering/config.local.yaml` (modify)
- **Where:** In the `pulse_metric_sources` section
- **What:** Point the `paid_customers` source at `company/funnel-state.json` (via `funnel-read.sh`) rather than the chimney scrape. Document the TTL and the `UNKNOWN` sentinel behavior inline.
- **Detail:** No new recurring spend introduced. This config change is documentation-level; the executable change is in Task 12.

### Task 14: PostHog read-back script (Phase B)

- **File:** `company/scripts/posthog-read.sh` (create)
- **Where:** New file alongside other collector scripts
- **What:** Queries the PostHog events/insights API for per-source `visit` and `checkout_click` event counts over a configurable time window (default 24 h) using a read-capable `POSTHOG_READ_KEY` credential (distinct from the write-only `POSTHOG_PROJECT_KEY`). Writes counts-only to stdout as JSON for the reconcile workflow to merge into the artifact. If the credential is missing or unauthorized, emits `{"status":"credential_missing"}` and exits 0 (non-breaching — top-of-funnel stages render `UNKNOWN` until Phase B credentials are provisioned). Never writes event payloads, user identities, or session data.
- **Detail:** Phase B dependency — this script is wired into `funnel-reconcile.yml` only after `POSTHOG_READ_KEY` is provisioned and Phase B top-of-funnel instrumentation ships. Until then, the artifact's `visit` and `checkout_click` stages remain `UNKNOWN`. No new recurring PostHog spend is introduced by this script alone; a paid PostHog tier (if needed for the insights API) requires human approval before provisioning.

### Task 15: PostHog read-back unit tests

- **File:** `company/scripts/test-posthog-read.sh` (create)
- **Where:** New file alongside other `test-*.sh` harnesses
- **What:** Covers: (a) query returns counts → top stages populated with source breakdown; (b) credential missing → `credential_missing` status, all top stages `UNKNOWN`, no error exit; (c) unauthorized → same as missing; (d) counts-only output — no event payloads or PII fields in output.
- **Detail:** Mocks `curl`. Asserts JSON output. No live API calls.

## Affected Files

company/scripts/polar-reconcile.sh                            (new)
company/scripts/test-polar-reconcile.sh                       (new)
company/funnel-state.json                                      (new)
company/scripts/funnel-read.sh                                 (new)
company/scripts/test-funnel-read.sh                            (new)
company/scripts/funnel-liveness.sh                             (new)
company/scripts/test-funnel-liveness.sh                        (new)
company/scripts/polar-synthetic-txn.sh                         (new)
company/scripts/test-polar-synthetic-txn.sh                    (new)
.github/workflows/funnel-reconcile.yml                         (new)      (no-test)
.github/workflows/heartbeat-pr-automerge.yml                   (modify)   (no-test)
.github/workflows/strategy-audit.yml                           (modify)   (no-test)
.compound-engineering/config.local.yaml                        (modify)   (no-test)
company/scripts/posthog-read.sh                                (new)
company/scripts/test-posthog-read.sh                           (new)

## Test Strategy

- `bash .github/scripts/validate-spec.sh specs/issue-1589-spec.md` passes with zero FAILs.
- `bash -n company/scripts/polar-reconcile.sh` passes (syntax clean).
- `bash company/scripts/test-polar-reconcile.sh` passes all scenarios including fetch-failure → `fetch_failed`, source normalization, host-mismatch failure.
- `bash -n company/scripts/funnel-read.sh` passes.
- `bash company/scripts/test-funnel-read.sh` passes: backdated `last_verified` → `UNKNOWN`, fresh → value, missing file → all `UNKNOWN`.
- `bash -n company/scripts/funnel-liveness.sh` passes.
- `bash company/scripts/test-funnel-liveness.sh` passes: breach → `fn:billing` issue opened once, UUID mismatch → breach, recovery → no duplicate issue.
- `bash -n company/scripts/polar-synthetic-txn.sh` passes.
- `bash company/scripts/test-polar-synthetic-txn.sh` passes: degraded heartbeat scenario covered, sandbox count isolation verified.
- `bash -n company/scripts/posthog-read.sh` passes.
- `bash company/scripts/test-posthog-read.sh` passes: missing credential → `UNKNOWN` top stages, no exit failure.
- After `funnel-reconcile.yml` runs: `company/funnel-state.json` on `main` has a `last_verified` within the last 24 h and `stages.paid.health` is `live` or `unknown` (never a stale numeric 0 with no timestamp).
- After `strategy-audit.yml` runs with a stale `funnel-state.json`: pulse report contains `UNKNOWN` for paid customers, not a numeric 0 or null.
- Pre-commit guard in `funnel-reconcile.yml`: injecting a `"amount":99` field into the artifact causes the commit step to abort and the workflow to fail.
- State-mutation assertion: a reconcile run that produces no content change exits non-zero on the assertion step.

## Estimated Complexity
high
