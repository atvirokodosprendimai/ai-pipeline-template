---
date: 2026-03-16T10:00:00Z
agent: claude
type: rca
issue: 458
tags: [observation-loop, hallucination, dedup, codebase-awareness]
status: resolved
outcome: success
---

## Summary

Root-caused and fixed observation loop creating bogus issues (wgmesh#458, #453) for features that already exist. The LLM had no visibility into the wgmesh codebase — only GitHub metadata — and concluded "no core product exists."

## Key Decisions

- Inject CLAUDE.md from wgmesh into loop LLM prompt as "Product Codebase Summary"
- Expand issue dedup to check both open AND closed issues (was open-only)
- Add explicit guardrail in system prompt: never create issues for existing features
- Generate episodic records externally for Copilot (can't rely on it writing memory files)

## Learnings

- Any LLM creating real-world artifacts MUST have ground-truth codebase context — metadata alone causes hallucination
- Issue dedup checking only open issues misses implemented-and-closed features
- Stale funnel stage in loop-state.json amplifies LLM hallucination

## Follow-up

- Advance loop-state.json funnel stage to reflect reality (Dogfood, not Foundation)
- Full shared memory subsystem to prevent similar isolation issues
