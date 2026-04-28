# MentisDB CI Integration Pattern

Use this pattern when a GitHub Actions workflow should leave durable agent-memory breadcrumbs in MentisDB.

## Endpoint

- Base URL comes from org secret `MENTISDB_URL`.
- Basic Auth credentials come from org secrets `MENTISDB_USER` and `MENTISDB_PASSWORD`.
- Normalize the URL before POSTing: `URL="${MENTISDB_URL%/}/v1/thoughts"`.
- POST JSON with `curl --fail-with-body --silent --show-error --max-time 15`.

## Chain

- Use `chain_key: "ai-pipeline-template"` for this repo.
- Use the workflow filename stem for `agent_id` and `agent_name`.
- Tags should be `["ai-pipeline-template", "<event-class>", "<outcome>"]` unless the workflow has a deliberate special case.
- Tags describe event semantics, not necessarily the exact workflow filename. Example: `spec-merged-build.yml` uses `agent_id="spec-merged-build"` and tag `spec-merge-build` because the event class is the transition from merged spec to build dispatch.

## Thought Types

- Successful state-changing workflow: `ActionTaken`, importance `0.5`.
- Completed work unit: `TaskComplete`, importance `0.7`.
- Periodic operational observation: `Insight`, importance `0.4`.
- Failed or cancelled lifecycle event: `Mistake`, importance `0.6` to `0.8` depending on severity.
- Do not use `Correction` unless the workflow actually applies a successful fix connected to a prior mistake.

## Failure Policy

- Lifecycle and observability appends are non-fatal. Preserve the workflow's primary outcome and emit a warning with curl exit code:

```bash
curl --fail-with-body --silent --show-error --max-time 15 \
  -u "$MENTISDB_USER:$MENTISDB_PASSWORD" \
  -X POST -H 'Content-Type: application/json' \
  -d "$PAYLOAD" "$URL" \
  || { code=$?; echo "::warning::mentisdb append failed (curl exit $code, non-fatal)"; }
```

- High-signal reference/smoketest workflows may keep the append fatal when the workflow's purpose is to validate MentisDB itself.
- High-frequency endpoint health should append only on failure to avoid flooding memory.

## Instrumented Workflows

- `bot-pr-review-merge.yml` -> `pr-review-merge`
- `heartbeat-pr-automerge.yml` -> `heartbeat-merge`
- `copilot-undraft.yml` -> `spec-undraft`
- `spec-validation.yml` -> `spec-validation`
- `approve-build.yml` -> `spec-approval`
- `spec-merged-build.yml` -> `spec-merge-build`
- `copilot-triage.yml` -> `issue-triage`
- `impl-merged-close.yml` -> `impl-close`
- `pipeline-health.yml` -> `pipeline-health`
- `health-check.yml` -> `endpoint-health` on failure only
- `observation-loop.yml` -> strategic assessment insight
- `mentisdb-smoketest.yml` -> daily round-trip verification

Not instrumented by design:

- `sync-labels.yml` is low-signal/high-noise.
- `terraform-deploy.yml` consumes `MENTISDB_PASSWORD` for infrastructure but does not emit lifecycle thoughts.

## Verification Query

After a workflow run, search by chain and event tag. Include the GitHub run URL in the thought content so duplicate retries can be deduplicated by run URL.
