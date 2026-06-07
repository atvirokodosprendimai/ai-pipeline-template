# wgmesh pipeline

Shadow-mode Python service for the autonomous wgmesh pipeline.

Phase 1 is intentionally safe by default:

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

