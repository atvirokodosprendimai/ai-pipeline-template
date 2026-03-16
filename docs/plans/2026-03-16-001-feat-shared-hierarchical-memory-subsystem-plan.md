---
title: "feat: Shared hierarchical memory subsystem for ai-pipeline"
type: feat
status: active
date: 2026-03-16
---

# feat: Shared hierarchical memory subsystem for ai-pipeline

## Overview

The autonomous pipeline operates four AI agents (observation loop LLM, Copilot SWE, Goose, Claude Code) that currently run in **total isolation** — zero shared memory, zero cross-session learning, zero feedback loops. Each agent starts every run from scratch, repeating mistakes and missing context that other agents already discovered.

This plan introduces a shared, file-based hierarchical memory subsystem stored in git. It enables cross-agent knowledge sharing, outcome-based feedback loops, and cumulative learning without external databases.

## Problem Statement

### Evidence

1. **Observation loop hallucination (wgmesh#458)**: The loop LLM concluded "no core product exists" and created greenfield issues for features shipping for months. Root cause: no codebase awareness. Fix applied, but the underlying problem — agents operating without shared context — remains.

2. **Goose is explicitly stateless**: Runs `--no-session`, meaning every implementation starts from scratch. Common pitfalls from `docs/solutions/` are never surfaced. Prior implementation patterns are invisible.

3. **3-assessment memory window**: The loop LLM sees only its last 3 assessments. Decisions from run #1 are invisible by run #5. No trend analysis, no pattern recognition across time.

4. **No feedback loop**: When Goose implements a spec and the PR merges, the observation loop sees it only as "+1 merged PR." It doesn't know what was implemented, whether the spec was followed, or what went wrong during implementation.

### Current State (Agent Isolation Map)

| Agent | Reads | Writes | Memory |
|-------|-------|--------|--------|
| **Observation Loop** | system-prompt.md, loop-state.json, last 3 assessments, wgmesh CLAUDE.md, GitHub signals | assessment, loop-state.json | 3-run window |
| **Copilot SWE** | copilot-instructions.md, issue body | spec PR | None |
| **Goose** | .goosehints, spec file, codebase | implementation PR | None (--no-session) |
| **Claude Code** | CLAUDE.md, memory/, docs/ | memory files, code | Session-only |

## Proposed Solution

### Architecture: Two Layers First

Based on SpecFlow analysis, defer working memory and procedural memory — they are underspecified and their value is unclear for stateless agents. Build **episodic + semantic** first, validate, then layer in more if needed.

```
memory/
├── MEMORY.md                              # Semantic layer — curated knowledge (always loaded)
├── episodic/                              # Episodic layer — session logs and outcomes
│   ├── 20260316-0937-loop-daily-assessment.md
│   ├── 20260316-1042-goose-implement-issue-457.md
│   ├── 20260316-1105-copilot-spec-issue-458.md
│   └── 20260316-1430-claude-nat-relay-rca.md
└── archive/                               # Consolidated entries (after promotion)
docs/solutions/                            # Procedural knowledge (existing, unchanged)
```

### Layer 1: Episodic Memory

**What**: Structured records of what each agent did, decided, and learned — one file per agent run.

**Schema** (YAML frontmatter + markdown body):

```yaml
---
date: 2026-03-16T09:37:00Z
agent: loop | copilot | goose | claude
type: assessment | spec | implementation | session | rca
issue: 457                    # optional, links to wgmesh issue
tags: [nat, relay, routing]   # for retrieval filtering
status: active | consolidated
outcome: success | failure | partial
---

## Summary
One-paragraph description of what happened.

## Key Decisions
- Decision 1 and rationale
- Decision 2 and rationale

## Learnings
- What worked and why
- What didn't work and why

## Follow-up
- Tasks generated
- Questions raised
```

**Producers**: Each agent writes one episodic file per run.
**Consumers**: All agents read recent/relevant episodic files before acting.

### Layer 2: Semantic Memory

**What**: `memory/MEMORY.md` — a curated, compact knowledge base distilled from episodic entries. Always loaded into every agent's context. Hard-capped at **4KB** to fit any agent's context budget.

**Structure**:

```markdown
# Memory

## Product State
- wgmesh is at Dogfood stage (functional, used internally)
- 4 discovery layers: GitHub Registry, LAN Multicast, DHT, Gossip
- NAT traversal, relay routing, encryption, RPC all implemented

## Known Issues & Patterns
- NAT relay flapping under intermittent connectivity (wgmesh#457)
- Single introducer is a bottleneck ("introducer busy" throttle)

## Agent Learnings
- LLMs creating artifacts MUST have ground-truth codebase context, not just metadata
- Issue dedup must check closed issues too (implemented features pass open-only filter)

## Pipeline Conventions
- Specs go through Copilot → Goose pipeline (label-driven)
- All code changes need tests (80%+ coverage target)
```

**Producers**: Consolidation process (promotes episodic → semantic).
**Consumers**: Every agent, every run.

## Technical Approach

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Shared Memory Store (git)                  │
│                                                               │
│  memory/MEMORY.md          memory/episodic/*.md               │
│  (semantic, 4KB cap)       (append-only, per-run)             │
│                                                               │
│  docs/solutions/*.md       company/loop-state.json            │
│  (procedural, existing)    (funnel state, existing)           │
└──────────┬──────────────────────────┬────────────────────────┘
           │                          │
    ┌──────┴──────┐           ┌───────┴───────┐
    │   READ      │           │   WRITE       │
    │             │           │               │
    ▼             ▼           ▼               ▼
┌────────┐ ┌──────────┐ ┌─────────┐ ┌────────────┐
│  Loop  │ │  Goose   │ │ Copilot │ │ Claude Code│
│  LLM   │ │          │ │  SWE    │ │            │
└───┬────┘ └────┬─────┘ └────┬────┘ └─────┬──────┘
    │           │            │             │
    ▼           ▼            ▼             ▼
  writes      writes       writes*       writes
  episodic    episodic     (external)    episodic
```

*Copilot writes are generated externally (see Phase 2 design decision).

### Implementation Phases

#### Phase 1: Memory Infrastructure (collect-memory.sh + episodic schema)

**Goal**: Create the retrieval script and episodic schema so memory can be read/written by any workflow.

**Tasks**:
1. [x] Create `company/scripts/collect-memory.sh` — reads `memory/MEMORY.md` + filters recent episodic entries by date/tags, outputs context-budget-aware text (truncates at configurable KB limit)
2. [x] Define episodic memory YAML schema (as above)
3. [x] Create `memory/MEMORY.md` with initial semantic content (product state, agent learnings from today's RCA)
4. [x] Create `memory/episodic/` directory
5. [x] Migrate existing `memory/*.md` files into `memory/episodic/` with proper frontmatter
6. [x] Run `sanitise.sh` validation on all memory files

**Success criteria**:
- `bash company/scripts/collect-memory.sh --budget 4096 --tags "nat,relay"` returns filtered, budget-capped memory content
- `bash company/scripts/collect-memory.sh --semantic-only` returns MEMORY.md content
- All memory files pass sanitisation

**Estimated effort**: Small (1-2 sessions)

#### Phase 2: Observation Loop Integration (read + write memory)

**Goal**: The observation loop reads memory before assessing and writes episodic memory after.

**Tasks**:
1. Add `collect-memory.sh` call to observation-loop.yml (after existing collect steps)
2. Inject memory output into LLM user message (new "## Shared Memory" section)
3. After LLM assessment, generate episodic memory file from the assessment JSON
4. Include episodic file in the branch+PR commit (alongside loop-state.json and assessment)
5. Add sanitisation step for memory files
6. Set context budget: 4KB semantic + 2KB episodic (latest 3 entries)

**Design decision — observation loop episodic write**:
The loop already commits via branch → PR → review → merge. Add memory files to the same commit. Copilot review covers them alongside the assessment. No separate PR flow needed.

**Success criteria**:
- Loop LLM user message includes semantic memory and recent episodic entries
- Each loop run produces `memory/episodic/YYYYMMDD-HHMM-loop-daily-assessment.md`
- Memory content passes sanitisation before commit
- Assessment quality improves (no bogus issues, better continuity between runs)

**Estimated effort**: Medium (1-2 sessions)

#### Phase 3: Goose Integration (read memory before implementing)

**Goal**: Goose reads relevant memory before starting implementation.

**Tasks**:
1. In goose-build.yml, call `collect-memory.sh --budget 3072 --tags "$(extract_tags_from_spec)"` before building the Goose task file
2. Inject memory output into `/tmp/goose-task.md` as a "## Prior Knowledge" section
3. After Goose completes, generate episodic memory file from the PR diff and implementation outcome
4. Include episodic file in Goose's implementation commit
5. Set context budget: 3KB total (semantic + filtered episodic)

**Design decision — relevance filtering for Goose**:
Extract tags from the spec file's YAML frontmatter (or from issue labels). Pass tags to `collect-memory.sh` which filters episodic entries by matching tags. This is deterministic and cheap — no LLM call needed for retrieval.

**Design decision — Goose episodic write**:
Generate the episodic record in the workflow AFTER Goose finishes (not inside Goose). Parse the PR diff, test results, and Goose's session output to create a structured record. This avoids depending on Goose's unreliable memory-writing behavior.

**Success criteria**:
- Goose task file includes relevant prior knowledge
- Each Goose run produces `memory/episodic/YYYYMMDD-HHMM-goose-implement-issue-N.md`
- Implementation quality improves (fewer repeated mistakes)

**Estimated effort**: Medium (1-2 sessions)

#### Phase 4: Copilot Integration (external episodic generation)

**Goal**: Copilot benefits from memory (reads) and contributes to it (writes — externally generated).

**Tasks**:
1. In copilot-triage.yml, inject memory summary into `custom_instructions` string (budget: 2KB)
2. After Copilot creates a spec PR, a workflow step generates the episodic memory file from the PR contents
3. Add episodic file to a follow-up commit on Copilot's branch (via GitHub API)

**Design decision — Copilot cannot reliably write memory**:
Copilot SWE is a black box. Current instructions say "The PR should contain ONLY the spec file." Changing this is fragile. Instead, generate Copilot's episodic record externally from the PR diff. This is reliable and doesn't depend on Copilot's compliance.

**Design decision — memory in custom_instructions**:
Copilot reads `custom_instructions` + `.github/copilot-instructions.md`. We can inject a compact memory summary into the `custom_instructions` string. Budget is tight — keep to 2KB of the most relevant semantic memory.

**Success criteria**:
- Copilot receives memory context in its instructions
- Each Copilot run produces an episodic file (generated externally from PR)
- Spec quality improves (references prior patterns, avoids known issues)

**Estimated effort**: Medium (1-2 sessions)

#### Phase 5: Consolidation Process (episodic → semantic promotion)

**Goal**: Periodically distill episodic entries into curated semantic memory.

**Tasks**:
1. Create `company/scripts/consolidate-memory.sh` — reads all `status: active` episodic entries, calls LLM to summarize key learnings, proposes updates to MEMORY.md
2. Add consolidation as a weekly step in the observation loop (Saturday runs, or every 7th run)
3. Consolidation output goes through the same branch+PR+review flow
4. After promotion, tag source episodic entries with `status: consolidated`
5. Entries older than 90 days AND consolidated get moved to `memory/archive/`

**Design decision — consolidation trigger**:
Weekly, within the observation loop. Not a separate workflow. The loop already has the LLM call infrastructure, PR flow, and sanitisation. Adding a conditional consolidation step is simpler than a new workflow.

**Design decision — staged promotion**:
Consolidation proposes changes to MEMORY.md via PR. Copilot reviews the PR. This creates a human-visible review gate before knowledge enters the semantic layer. Prevents LLM memory poisoning (a high-severity risk identified in SpecFlow analysis).

**Design decision — archive, don't delete**:
Consolidated episodic entries move to `memory/archive/` rather than being deleted. Git history preserves everything, but archival keeps the active episodic directory manageable and reduces retrieval noise.

**Success criteria**:
- MEMORY.md stays under 4KB
- Consolidation runs weekly without errors
- Key learnings from episodic entries appear in MEMORY.md
- Archived entries are accessible but don't pollute active retrieval

**Estimated effort**: Medium-Large (2-3 sessions)

#### Phase 6: Feedback Loops (outcome tracking)

**Goal**: Implementation outcomes flow back to inform future planning.

**Tasks**:
1. Extend Goose episodic records to include structured outcome data: CI pass/fail, test coverage delta, review comments, merge status
2. Extend observation loop to correlate assessment actions with outcomes: "I created issue #457 → Goose implemented it → PR merged → tests pass → route flapping fixed (or not)"
3. Add outcome summary to the consolidation LLM prompt so learnings include "what worked"
4. Track pattern metrics: which types of issues succeed on first implementation? Which need multiple attempts?

**Design decision — outcome data source**:
GitHub API already provides PR merge status, CI check results, and review comments. The observation loop's `collect-github.sh` already queries some of this. Extend it to collect per-issue outcome data for issues created by the loop.

**Success criteria**:
- Episodic records include outcome data (not just what was attempted)
- Consolidation produces learnings like "approach X works for problem type Y"
- Loop assessment quality improves over time (measurable via fewer bogus issues, better action prioritization)

**Estimated effort**: Large (2-4 sessions)

## Alternative Approaches Considered

### Vector database (Pinecone/Chroma/Qdrant)

**Rejected.** Adds infrastructure cost ($50-200/mo), vendor dependency, and operational complexity. At the scale of this pipeline (<1000 knowledge entries), file-based grep/tag filtering achieves equivalent retrieval quality at zero cost. Markdown files in git are transparent, version-controlled, and human-editable.

### LLM summarization for context management

**Partially adopted.** JetBrains research (Dec 2025) found observation masking outperforms LLM summarization in 4/5 settings while costing 7% less. We use summarization only for consolidation (episodic → semantic), not for context injection. For injection, we use budget-capped filtering (simpler, cheaper, deterministic).

### Google A2A protocol for agent communication

**Deferred.** A2A (v0.3, 150+ orgs) is the right long-term direction for inter-agent communication, but overkill for 4 agents sharing a git repo. Revisit when the pipeline scales to multiple concurrent products or real-time coordination is needed.

### Single shared MEMORY.md with no episodic layer

**Rejected.** Without episodic memory, there's no raw material for consolidation, no audit trail, and no way to trace where knowledge came from. Semantic memory alone is static — it doesn't learn.

## System-Wide Impact

### Interaction Graph

Memory read happens early in each workflow:
- Observation loop: `collect-memory.sh` → inject into user message → LLM call → write episodic → commit
- Goose: `collect-memory.sh` → inject into task file → Goose runs → write episodic → commit
- Copilot: inject into `custom_instructions` → Copilot runs → external episodic generation → commit

No new callbacks, middleware, or observers. Memory is injected as text into existing prompts.

### Error Propagation

- If `collect-memory.sh` fails: workflow continues without memory (graceful degradation, warning logged)
- If episodic write fails: workflow continues, no memory recorded for this run (acceptable loss)
- If MEMORY.md is corrupted: git revert to previous version (human intervention)
- If consolidation produces bad content: caught by PR review gate before merge

### State Lifecycle Risks

- **Memory poisoning**: LLM writes wrong conclusion → promoted to semantic → all agents inherit mistake. Mitigated by PR review gate on consolidation and `status: consolidated` tagging.
- **Stale semantic memory**: MEMORY.md says "NAT works" but reality changed. Mitigated by weekly consolidation refreshing from recent episodic entries.
- **Concurrent writes**: Two agents commit memory files simultaneously. Mitigated by one-file-per-entry (no shared mutable files for episodic layer). MEMORY.md conflicts mitigated by single-writer consolidation process.

### API Surface Parity

All four agents get memory through the same mechanism: text injected into their prompt/instructions. No agent-specific memory API. `collect-memory.sh` is the single retrieval interface.

### Integration Test Scenarios

1. **Loop reads memory from prior run**: Run loop twice. Second run's assessment should reference learnings from first run's episodic entry.
2. **Goose reads relevant memory**: Create episodic entry about a specific issue. Run Goose on that issue. Verify task file contains the relevant memory.
3. **Consolidation promotes correctly**: Create 10 episodic entries. Run consolidation. Verify MEMORY.md contains distilled insights and source entries are tagged `consolidated`.
4. **Concurrent safety**: Trigger loop and Goose simultaneously. Verify both PRs merge without conflict (separate episodic files).
5. **Context budget respected**: Fill episodic directory with 100 entries. Verify `collect-memory.sh --budget 4096` returns ≤4KB.

## Acceptance Criteria

### Functional Requirements

- [ ] `memory/MEMORY.md` exists with curated semantic knowledge, hard-capped at 4KB
- [ ] `memory/episodic/` contains structured per-run records with YAML frontmatter schema
- [ ] `company/scripts/collect-memory.sh` retrieves memory with budget and tag filtering
- [ ] Observation loop reads memory before LLM call and writes episodic after
- [ ] Goose reads relevant memory before implementation and episodic is generated after
- [ ] Copilot receives memory in custom_instructions and episodic is generated externally
- [ ] Weekly consolidation promotes episodic insights to semantic memory via PR
- [ ] All memory writes pass `sanitise.sh` before commit to public repo

### Non-Functional Requirements

- [ ] Memory retrieval adds <2s to workflow execution time
- [ ] No external database or API dependency (file-based, git-native)
- [ ] Graceful degradation: if memory is unavailable, agents proceed without it
- [ ] Context budgets enforced: 4KB semantic + 2-3KB episodic per agent
- [ ] Episodic entries archived after 90 days + consolidation

### Quality Gates

- [ ] collect-memory.sh has unit tests (bash assertions on output format and budget compliance)
- [ ] Observation loop integration tested via manual workflow_dispatch
- [ ] Goose integration tested via manual approved-for-build trigger
- [ ] Consolidation tested with synthetic episodic entries
- [ ] Memory files validated against schema (YAML frontmatter required fields present)

## Success Metrics

| Metric | Baseline (now) | Target (Phase 5 complete) |
|--------|----------------|---------------------------|
| Bogus issues created by loop | 2 in 6 runs | 0 |
| Loop assessment continuity | 3-run window | Full history via semantic memory |
| Goose first-attempt success rate | Unknown | Tracked, improving |
| Repeated mistakes across agents | Frequent (no shared learning) | Rare (surfaced via memory) |
| Agent context quality | Metadata-only | Metadata + codebase + memory |

## Dependencies & Prerequisites

- **Phase 1** has no dependencies (standalone script + directory structure)
- **Phase 2** depends on Phase 1 (collect-memory.sh must exist)
- **Phase 3** depends on Phase 1 (same retrieval script)
- **Phase 4** depends on Phase 1 (same retrieval script)
- **Phase 5** depends on Phases 2-4 (needs episodic entries from all agents to consolidate)
- **Phase 6** depends on Phase 5 (outcome tracking builds on consolidation)

Phases 2, 3, 4 can run **in parallel** after Phase 1 completes.

## Risk Analysis & Mitigation

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| LLM memory poisoning (wrong knowledge promoted) | High | Medium | PR review gate on consolidation; `status` field for staged promotion |
| Context window starvation | Medium | Medium | Hard budget caps per agent; `collect-memory.sh` truncates at limit |
| Copilot ignores memory instructions | High | High | Don't depend on Copilot — generate episodic externally from PR |
| Concurrent write conflicts | Medium | Low | One file per episodic entry; MEMORY.md single-writer (consolidation only) |
| Repository bloat from episodic files | Low | Medium | 90-day archival policy; archive directory for old entries |
| Sanitisation miss (sensitive data in memory) | High | Low | All memory writes go through `sanitise.sh`; PR review as second gate |

## Future Considerations

- **Procedural memory layer**: `docs/solutions/` already serves this role. If retrieval needs grow, add YAML frontmatter to solution files and include them in `collect-memory.sh` filtering.
- **Working memory**: Only relevant for Claude Code (the only stateful agent). Consider gitignored `memory/working/` for session scratch files.
- **A2A protocol**: When pipeline scales to multiple products or real-time agent coordination, evaluate Google A2A for structured inter-agent communication.
- **Vector search**: If episodic entries exceed 1000, evaluate SQLite FTS or lightweight embedding search. Current tag-based filtering scales to ~500 entries comfortably.
- **Cross-repo memory**: If the template is used for multiple products, namespace memory per-product (e.g., `memory/wgmesh/`, `memory/lighthouse/`).

## Documentation Plan

- Update `README.md` with memory subsystem overview
- Update `company/system-prompt.md` with memory reading instructions
- Update `.goosehints` with memory file references
- Update `.github/copilot-instructions.md` with memory awareness
- Add `memory/README.md` explaining schema and conventions

## Sources & References

### Internal References

- RCA: `docs/solutions/logic-errors/observation-loop-creates-bogus-issues-for-existing-features.md`
- Observation loop: `.github/workflows/observation-loop.yml`
- Goose build: `.github/workflows/goose-build.yml`
- Copilot triage: `.github/workflows/copilot-triage.yml`
- System prompt: `company/system-prompt.md`
- Existing memory files: `memory/*.md`

### External References

- JetBrains Research: Efficient Context Management for SWE Agents (Dec 2025) — observation masking vs summarization
- CrewAI Memory System: Unified Memory with scoped paths and composite scoring
- LangGraph Store: Cross-thread state sharing via namespaced key-value store
- Google A2A Protocol v0.3: Inter-agent communication standard (150+ orgs)
- "AI Agent Memory Management: When Markdown Files Are All You Need" — file-based pattern validation
- Anthropic: Effective Harnesses for Long-Running Agents — memory flush before compression

### Related Work

- wgmesh#458 (closed): Bogus issue created by loop — triggered this initiative
- wgmesh#453 (closed): Bogus MVP spec — same root cause
- Commit `639dca7`: Fix that added codebase awareness to loop (precursor to full memory)
