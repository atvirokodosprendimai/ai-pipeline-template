---
tldr: Two-layer endpoint monitoring — 15-minute curl probes with GitHub issue lifecycle management, feeding raw signals into the observation loop.
category: core
---

# Infrastructure Monitoring

## Target

Detect service outages within 15 minutes and surface them as actionable GitHub issues — without human polling, without LLM overhead, and without false positives that require manual cleanup. Recovery must be self-evident: the issue closes itself when all endpoints are back.

## Behaviour

- Probes every registered endpoint on a 15-minute cron cadence. {>> The cron is the heartbeat — any gap longer than 15 min is itself a signal of pipeline failure.}
- Measures latency in milliseconds for every probe, regardless of outcome. {>> Latency is collected even on success so trending degradation is visible before full outage.}
- Classifies each endpoint into exactly three states: `up` (HTTP 2xx–3xx), `unreachable` (curl exit / connection timeout), or `error:<http_code>` (unexpected HTTP response). {>> No ambiguous "degraded" state — the classification must be stable across reruns of the same condition.}
- On first failure: creates a GitHub issue labelled `health-check` and `needs-human`. {>> `needs-human` is the signal to the OODA loop that autonomous recovery is not available here — human escalation is required.}
- On subsequent consecutive failures with an existing open issue: appends a timestamped comment rather than opening a duplicate. {>> Idempotent by design — duplicate issues would saturate the issue tracker and obscure signal.}
- On full recovery (all endpoints `up`): auto-closes the open `health-check` issue with a recovery timestamp comment. {>> Closure is automatic — no human action required to confirm recovery.}
- When all endpoints are healthy and no open issue exists: the workflow exits silently with no side effects.
- Endpoint registry is the single source of truth for what is monitored. {>> Adding or removing a monitored service requires only a `company/health.json` edit — no workflow changes.}
- Emits a structured JSON payload (source, collected\_at, services array) to stdout for downstream consumption by the observation loop.
- Uses sparse checkout to fetch only `company/health.json` and `company/scripts/collect-infra.sh`. {>> Sparse checkout keeps the job fast and avoids cloning large repo history every 15 minutes.}
- Requires no LLM calls, no secrets beyond `GITHUB_TOKEN`, and no external dependencies beyond `curl`, `jq`, and `gh`. {>> Deliberate minimalism — the health layer must remain operational even when the rest of the pipeline is degraded.}

## Design

**Two distinct layers with different purposes.** The health-check workflow is a rapid-response alerting layer: binary pass/fail, GitHub issues as the notification channel, no heavy processing. The `collect-infra.sh` script is a structured data collector whose JSON output is the contract with the observation loop — it can be run independently of the alerting path.

**Configuration as data, not code.** Endpoints live in `company/health.json` as a plain array of `{name, url}` objects. This means the monitoring scope can be changed by any process that can write JSON — including the OODA loop itself — without touching workflow YAML.

**Stateless issue deduplication via label query.** The workflow does not maintain external state. It queries `gh issue list --label "health-check" --state open` at runtime to determine whether an active incident already exists. This means the alerting state is always derivable from GitHub's issue tracker, and the workflow is safe to run concurrently or re-trigger manually.

**Latency via nanosecond wall-clock diff.** `date +%s%N` before and after `curl` provides millisecond-resolution latency without requiring any additional tooling. The result degrades gracefully on systems where `%N` is unsupported (returns 0), preserving the probe result without erroring.

**HTTP success range is 2xx–3xx.** Redirects are treated as healthy. This is intentional: many production services return 301/302 before the client follows to the real endpoint.

## Interactions

- [[spec - observation loop - autonomous OODA cycle for company operations]] — the structured JSON payload from `collect-infra.sh` is ingested by the observation loop as raw infrastructure signal.
- [[spec - self healing - deterministic pipeline recovery]] — `needs-human` label on health-check issues signals that self-healing cannot resolve the outage autonomously. However, self-healing DOES auto-close health-related `needs-human` issues when all endpoints in `health.json` recover (resolution signal 3). The health-check workflow handles the `health-check`-labelled issue lifecycle; self-healing handles the `needs-human` escalation lifecycle.

## Mapping

Source files:

- `.github/workflows/health-check.yml` — scheduling, sparse checkout, issue lifecycle (create / comment / close)
- `company/scripts/collect-infra.sh` — curl probe logic, latency measurement, JSON output contract
- `company/health.json` — endpoint registry (name + url per service)
