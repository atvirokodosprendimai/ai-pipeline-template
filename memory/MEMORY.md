# Memory

Curated knowledge for all pipeline agents. Hard cap: 4KB.
Last consolidated: 2026-04-10.

## Product State

- **wgmesh** is at Dogfood stage (day 23, entered 2026-03-18) — functional, used internally
- Architecture: Go 1.25, two modes (centralized + decentralized)
- 4 discovery layers: L0 GitHub Registry, L1 LAN Multicast, L2 BitTorrent DHT, L3 In-Mesh Gossip
- NAT traversal (STUN + hole-punching), relay routing with hysteresis (PR #464), AES-256-GCM encryption, JSON-RPC 2.0
- CLI + daemon with 5-second reconcile loop, hot reload via SIGHUP
- Extracted repos: lighthouse (CDN control plane), lighthouse-go (SDK), chimney (GitHub proxy)
- Distribution: GoReleaser, Docker (ghcr.io), Homebrew tap
- Pipeline: 61 loop runs, 208 health checks, 4 monitored endpoints (chimney, cloudroof, coroot, tvcentras)
- NAT relay flapping (wgmesh#457) fixed 2026-04-10 — Dogfood stability clock started

## Known Issues

- Single introducer bottleneck — mitigated by PR #464 fallback logic, architectural fix deferred
- Testlab lacks reproducible NAT simulation — production mesh is only verified test method
- Observability metrics gap (wgmesh#470) — no Prometheus endpoint for mesh health data yet

## Agent Learnings

- LLMs creating real-world artifacts (issues, PRs) MUST have ground-truth codebase context, not just metadata — metadata alone causes hallucination (wgmesh#458 RCA)
- Issue dedup must check BOTH open AND closed issues — implemented features pass open-only filter
- Funnel stage in loop-state.json must reflect reality — stale stage amplifies LLM hallucination
- Copilot SWE agent cannot reliably write files outside its perceived scope — generate episodic records externally
- Copilot PR review times out after 360s — PRs needing review escalation to human must not sit indefinitely (PR #464 sat 19 days)
- March 15-17 assessments incorrectly reported Stage 0 (no product) due to missing codebase summary — trust code over prior assessments

## Pipeline Conventions

- Spec-first: issues → Copilot writes spec → human reviews → Goose implements
- Label-driven routing: `fn:dev` + `needs-triage` → Copilot, `approved-for-build` → Goose
- CI lifecycle workflows append typed thoughts to MentisDB chain `ai-pipeline-template`; see `memory/reference_mentisdb_ci_integration_pattern.md`
- All code needs tests (80%+ coverage target), table-driven t.Parallel() patterns in Go
- Public repo: never commit secrets, PII, or exact revenue figures
- Assessment PRs auto-merge only if Copilot review has zero comments and zero blocking reviews
- Multi-model routing: `STAGE_ROUTING`+`MODEL_REGISTRY` env (`pipeline/wgmesh_pipeline/models.py`) pick a model per stage (cheap=spec, capable=implement); hybrid billing (subs native, metered via OpenRouter); both unset → zero-config single z.ai model; fail-closed; per-model cost in Langfuse. Escalate-on-fail = Phase 2. Doc: `docs/solutions/design-decisions/multi-model-routing.md`
