---
date: 2026-03-16T09:54:00Z
agent: claude
type: rca
tags: [testlab, nat, testing, infrastructure]
status: active
outcome: partial
---

## Summary

Identified incoherence: testlab/README.md recommends "production mesh" as primary test method, but wgmesh#457 requires controlled NAT failure simulation to verify relay fallback, hysteresis, and --no-punching flag.

## Key Decisions

- This blocks autonomous pipeline verification of NAT-related fixes
- Options to resolve: iptables-based NAT simulation in cloud VMs, Lima with custom network namespaces, or mock-based unit tests (covers logic but not integration)

## Learnings

- Pipeline cannot autonomously verify NAT-related fixes without a reproducible test environment
- Mock-based unit tests cover logic but miss integration-level failures

## Follow-up

- Design testlab NAT simulation approach (cloud VMs vs local Lima)
