# Memory

Curated knowledge for all pipeline agents. Hard cap: 4KB.
Last consolidated: 2026-03-16 (initial seed from manual session).

## Product State

- **wgmesh** is at Dogfood stage — functional, used internally by beta testers
- Architecture: Go 1.25, two modes (centralized + decentralized)
- 4 discovery layers: L0 GitHub Registry, L1 LAN Multicast, L2 BitTorrent DHT, L3 In-Mesh Gossip
- NAT traversal (STUN + hole-punching), relay routing, AES-256-GCM encryption, JSON-RPC 2.0
- CLI + daemon with 5-second reconcile loop, hot reload via SIGHUP
- Extracted repos: lighthouse (CDN control plane), lighthouse-go (SDK), chimney (GitHub proxy)
- Distribution: GoReleaser, Docker (ghcr.io), Homebrew tap

## Known Issues

- NAT relay flapping under intermittent connectivity — routes oscillate between direct and relay (wgmesh#457)
- Single introducer bottleneck — "introducer busy" throttle blocks NAT traversal for new peers
- Testlab lacks reproducible NAT simulation — production mesh is only verified test method

## Agent Learnings

- LLMs creating real-world artifacts (issues, PRs) MUST have ground-truth codebase context, not just metadata — metadata alone causes hallucination (wgmesh#458 RCA)
- Issue dedup must check BOTH open AND closed issues — implemented features pass open-only filter
- Funnel stage in loop-state.json must reflect reality — stale stage amplifies LLM hallucination
- Copilot SWE agent cannot reliably write files outside its perceived scope — generate episodic records externally

## Pipeline Conventions

- Spec-first: issues → Copilot writes spec → human reviews → Goose implements
- Label-driven routing: `fn:dev` + `needs-triage` → Copilot, `approved-for-build` → Goose
- All code needs tests (80%+ coverage target), table-driven t.Parallel() patterns in Go
- Public repo: never commit secrets, PII, or exact revenue figures
- Assessment PRs auto-merge only if Copilot review has zero comments and zero blocking reviews
