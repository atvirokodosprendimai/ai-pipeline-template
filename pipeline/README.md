# wgmesh pipeline

Python service for the autonomous wgmesh pipeline.

`PIPELINE_MODE=live` is the current production mode for the `wgmesh-pipeline`
box on Hetzner. `spec-only` and `shadow` remain fallback/rollback modes.
`spec_opened` rows resume at `spec_ready` when a live-mode box picks them up.

Phase 1 was intentionally safe by default:

- `PIPELINE_MODE` defaults to `shadow`.
- GitHub writes must route through `wgmesh_pipeline.github.client.GitHubClient`.
- Shadow-mode writes are recorded as dry-run events and perform no network side effects.
- Live external services are mocked in tests.

Minimal local setup:

```bash
python3 -m venv pipeline/.venv
source pipeline/.venv/bin/activate
pip install -e pipeline/
pytest pipeline/tests/
```

## Fallback: spec-only live

Spec-only lets the box open real spec PRs for wgmesh and then stop. It is now a
rollback mode; GitHub Actions own spec review, build, code review, and merge.

Run from the repo root:

```bash
source pipeline/.venv/bin/activate
export PIPELINE_MODE=spec-only
export TARGET_REPO=atvirokodosprendimai/wgmesh
export WGMESH_BOT_PAT=<bot token with repo write access>
export ZAI_API_KEY=<optional, for Goose-backed spec generation>
wgmesh-pipeline
```

In `PIPELINE_MODE=spec-only`, the graph runs:

```text
triage -> spec -> spec_pr -> halt
```

`spec_pr` pushes `bot/spec-N`, opens a PR titled exactly
`spec: Issue #N - <title>`, then moves the issue label from `needs-triage` to
`copilot-triaging`. Implementation and gate nodes are not run in this mode.

`PIPELINE_MODE=shadow` still performs no network writes; the spec PR step is recorded as
dry-run operations and the graph continues through implement, review, and gate. `live`
continues through the full Phase 3 path.

## Spec parity harness

The parity harness is read-only: it does not create PRs, change labels, or write to
GitHub. Give it one or more existing Actions-produced spec files to compare against:

```bash
source pipeline/.venv/bin/activate
python pipeline/evals/spec_parity.py \
  --repo-path /path/to/wgmesh \
  --reference 123=/path/to/reference/spec.md \
  --reference 124=/path/to/another/reference.md
```

Each issue emits one JSON parity report with structural status, missing required sections
if any, and an LLM-as-judge similarity score. Tests inject the spec generator and judge so
they never call live Goose, GitHub, or network services.
