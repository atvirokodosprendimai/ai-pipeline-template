---
tldr: Coherence report across 7 pipeline specs — contradictions, orphaned links, missing cross-refs
category: core
---

# Coherence: Full spec graph after initial pull

## Contradictions

### C1 — Build agent identity: Copilot vs Goose

- **Observation loop spec** and **system-prompt.md** describe Goose as the build agent
- **Pipeline state machine spec** (line 22) says "Copilot is re-assigned with instructions to read the merged spec and produce an implementation PR" in the build phase
- **Code reality** (`spec-merged-build.yml` line 39): assigns `copilot-swe-agent[bot]` for implementation, not Goose
- **README** describes Goose as the default build agent but notes "Swap any agent"
- This is not strictly a contradiction — the template supports both — but the pipeline SM spec should clarify that the build agent is configurable and currently defaults to Copilot assignment via the agent API

**Resolved:** Pipeline SM spec updated to clarify the build agent role is configurable, currently defaults to Copilot.

### C2 — PR review merge: protected paths default

- **PR review merge spec** (line 23): "PRs touching protected path prefixes are blocked ... by default covers `.github/` and `company/scripts/`"
- **Code reality** (`pr-review-merge.sh` line 16): `PROTECTED_PATHS="${PROTECTED_PATHS:-}"` — default is **empty**
- The spec claims a default that the code does not enforce. Either the spec should say "empty by default, configurable" or the code should set a default.

**Resolved:** PR review merge spec updated to say "empty by default, configurable".

### C3 — PR merge: exit codes

- **PR review merge spec** (line 33): "exit 0 on both successful merge and successful escalation; exit 1 is reserved for fatal infrastructure failure"
- **PR review merge spec** (line 30): "circuit breaker halts the script with exit 1 after five cumulative errors"
- These are consistent (circuit breaker IS a fatal infrastructure failure), but should be explicitly reconciled in the spec to avoid reader confusion.

**Resolved:** Exit code semantics clarified — escalation is exit 0 (successful outcome), circuit breaker is exit 1 (unrecoverable).

## Orphaned Links

### O1 — Security quality spec references non-existent specs

The security quality spec's Interactions section references specs that don't match actual filenames:

- `[[spec - observation loop]]` — should be `[[spec - observation loop - autonomous OODA cycle for company operations]]`
- `[[spec - pipeline health]]` — should be `[[spec - self healing - deterministic pipeline recovery]]`
- `[[spec - pr review merge]]` — should be `[[spec - pr review merge - autonomous bot pr guardrails]]`
- `[[spec - state management]]` — does not exist (no standalone state management spec)
- `[[spec - audit log]]` — does not exist (covered within self-healing and PR review specs)
- `[[spec - dashboard]]` — does not exist (chimney is a separate repo)
- `[[spec - testing]]` — should be `[[spec - testing - e2e and integration test framework]]`
- `[[spec - conventional commits]]` — does not exist (covered by QUAL-4 in the Constitution itself)

**Resolved:** All 8 links fixed — renamed to full spec names, replaced non-existent specs with inline descriptions.

### O2 — Infrastructure monitoring: self-healing interaction claim

- Infra monitoring spec says self-healing "does not attempt to auto-close" health-check issues
- Self-healing spec says needs-human auto-close checks for health endpoint resolution (signal 3: title contains `health` or `endpoint`)
- These are describing the same mechanism from different angles — not contradictory, but the infra spec should acknowledge the auto-close path exists

**Resolved:** Infra monitoring spec updated to acknowledge self-healing's auto-close of health-related needs-human issues.

## Missing Cross-References

### M1 — Observation loop ↔ PR review merge

- Observation loop produces PRs that flow through bot-pr-review-merge
- Observation loop spec mentions "bot-pr-review-merge workflow" in prose but does NOT list `[[spec - pr review merge - autonomous bot pr guardrails]]` in its Related specs
- Should add the wiki link

**Resolved:** Added `[[spec - pr review merge - autonomous bot pr guardrails]]` to observation loop's Related specs.

### M2 — Pipeline state machine ↔ Security quality

- Pipeline state machine uses sanitise.sh implicitly (via copilot-triage input sanitisation)
- No link to `[[spec - security quality - constitution and enforcement]]` in its Interactions
- Should add the link

**Resolved:** Added security quality cross-ref to pipeline state machine Interactions.

### M3 — Testing ↔ Observation loop

- `test-collect-memory.sh` tests the memory collection that feeds the observation loop
- Testing spec does not reference `[[spec - observation loop - autonomous OODA cycle for company operations]]`
- Low priority — indirect dependency

**Deferred:** Indirect dependency — adding the link would imply a stronger coupling than exists.

### M4 — Infrastructure monitoring ↔ Security quality

- Health check workflow uses `GITHUB_TOKEN` permissions (SEC-4)
- No link to `[[spec - security quality - constitution and enforcement]]`
- Low priority — all specs implicitly depend on the Constitution

**Deferred:** All specs implicitly depend on the Constitution — adding explicit links everywhere would be noise.

## CLAUDE.md Candidates

### CL1 — "Andon: no silent failures"

Appears explicitly in: security quality spec, self-healing spec, PR review merge spec.
Referenced implicitly in: observation loop spec (fail-safe degradation), testing spec (no silent test failures).
This is already in CONSTITUTION.md. No action needed — the Constitution IS the enforcement mechanism.

### CL2 — "sanitise.sh before all public output"

Referenced in: observation loop, self-healing, PR review merge, security quality.
Already codified as SEC-2 in CONSTITUTION.md. No additional CLAUDE.md entry needed.

### CL3 — "Issues are the API to the pipeline"

Stated in observation loop spec Design section. Implicit in pipeline state machine and self-healing specs.
This is a core architectural principle worth adding to CLAUDE.md if not already present.

**Deferred:** Worth considering but CLAUDE.md in this repo is minimal — would need a broader CLAUDE.md overhaul.

## Summary

- **7 specs analysed**
- **2 contradictions** found (C1: build agent identity, C2: protected paths default)
- **1 near-contradiction** noted (C3: exit codes — consistent but unclear)
- **8 orphaned links** (all in security quality spec's Interactions — used short names instead of full spec names)
- **4 missing cross-references** (M1–M4)
- **3 CLAUDE.md candidates evaluated** (2 already covered by Constitution, 1 worth considering)
