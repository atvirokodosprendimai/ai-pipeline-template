---
date: 2026-03-16T09:54:00Z
agent: claude
type: session
issue: 457
tags: [nat, relay, routing, implementation]
status: active
outcome: partial
---

## Summary

Created implementation task for wgmesh#457 — NAT relay flapping fix with 3 deliverables: `--no-punching` flag, route stability hysteresis, and multi-introducer fallback.

## Key Decisions

- TDD approach: write 9 test cases RED before any implementation
- Affected packages: pkg/daemon, pkg/discovery, pkg/daemon/routes.go

## Follow-up

- Write tests first (routes_test.go, config_test.go, dht_test.go, daemon_test.go)
- Then implement the 3 deliverables
