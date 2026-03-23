---
tldr: Weave suggestions — 4 potential links discovered, graph already well-connected
category: core
---

# Weave: suggested links

1 - Self-healing → Observation loop (reverse link)
  - 1.1 - [[spec - self healing - deterministic pipeline recovery]] → [[spec - observation loop - autonomous OODA cycle for company operations]] — self-healing reads `loop-state.json` (observation loop's state) as a resolution signal for api-key needs-human issues. Already documented in self-healing's Interactions prose but missing the wiki link.

2 - Self-healing → Infrastructure monitoring (reverse link)
  - 2.1 - [[spec - self healing - deterministic pipeline recovery]] → [[spec - infrastructure monitoring - endpoint health and alerting]] — self-healing reads `health.json` for presence signals and health-related needs-human auto-close. Already documented in prose but missing the wiki link.

3 - Observation loop → Testing
  - 3.1 - [[spec - observation loop - autonomous OODA cycle for company operations]] → [[spec - testing - e2e and integration test framework]] — not needed. The testing spec tests memory collection (an observation loop dependency) but the observation loop itself doesn't depend on or interact with the test framework. No link warranted.

4 - Already well-connected (no action needed)
  - The security quality spec links to all 6 other specs (hub node) ✅
  - The observation loop links to 5/6 specs ✅
  - The pipeline state machine links to 4/6 specs ✅
  - Average connectivity: 3.4 links per spec — healthy for 7 nodes
