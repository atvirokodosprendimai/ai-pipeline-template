---
date: 2026-03-16T09:37:00Z
agent: claude
type: session
issue: 457
tags: [nat, relay, routing, issue-triage, beta-testing]
status: resolved
outcome: success
---

## Summary

Filed wgmesh#457 (NAT traversal failure causes route flapping when relay fallback doesn't activate) from anonymized beta tester chat logs. Included 9 specific test cases across 4 packages and 3 suggested improvements.

## Key Decisions

- Anonymized all personal info from chat logs before filing
- Included test strategy directly in the issue (not a separate spec) for faster pipeline pickup
- Proposed `--no-punching` flag, route hysteresis, and multi-introducer default as improvements

## Learnings

- Beta tester chat logs (even in Lithuanian) are a valuable source for real-world failure scenarios
- wgmesh relay fallback has no hysteresis — routes flap when NAT is intermittent
- Single introducer is a bottleneck — "introducer busy" throttle blocks NAT traversal

## Follow-up

- Implement wgmesh#457 (3 deliverables: no-punching flag, hysteresis, multi-introducer)
- Write 9 TDD test cases before implementation
- Testlab lacks reproducible NAT simulation — blocks autonomous verification
