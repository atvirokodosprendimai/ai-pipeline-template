---
title: "Phase 4: Integration and Validation"
status: completed
version: "1.0"
phase: 4
---

# Phase 4: Integration and Validation

## Phase Context

**GATE**: Read all referenced files before starting this phase.

**Specification References**:
- `[ref: SDD/Quality Requirements]` — Performance, usability, security, reliability targets
- `[ref: SDD/Acceptance Criteria]` — 12 EARS criteria
- `[ref: PRD/Success Metrics]` — KPIs and tracking requirements
- `[ref: SDD/Risks and Technical Debt]` — Known issues and gotchas to verify

**Key Decisions**:
- Performance targets: self-healing <5 min, dashboard <1.5s cached
- SLOs: >99% self-healing run success, <5% false positive rate
- All PRD acceptance criteria must be verifiable

**Dependencies**:
- Phase 1 complete — foundation infrastructure
- Phase 2 complete — self-healing checks operational
- Phase 3 complete — dashboard deployed

---

## Tasks

End-to-end integration testing across all components. After this phase, the full feature is validated, SLOs are baselined, and the spec is ready for release.

- [ ] **T4.1 Self-Healing End-to-End Test** `[activity: testing]` `[component: ai-pipeline-template]`

  1. Prime: Read all SDD acceptance criteria `[ref: SDD/Acceptance Criteria]`. Read PRD success metrics for healing success rate target (>90%) `[ref: PRD/Success Metrics]`.
  2. Test: Create artificial stale issues in wgmesh (or a test repo):
     - Issue with `needs-triage` label, created >24h ago → verify label toggle occurs
     - Issue with `copilot-triaging` label, no spec PR, >48h → verify re-assignment
     - PR with `approved-for-build`, no impl PR, >24h → verify re-trigger
     - `needs-human` issue with linked merged PR → verify auto-close
     - Trigger workflow_dispatch manually → verify full cycle completes
     - Verify pipeline-health-state.json updated with correct summary
     - Verify audit-log.jsonl has entries for all actions
     - Verify PR created with state changes
  3. Implement: Write test script or manual test procedure that:
     - Creates test issues with backdated labels (using GitHub API)
     - Triggers pipeline-health.yml via workflow_dispatch
     - Waits for completion
     - Verifies outcomes via GitHub API (label changes, issue closures, PR created)
     - Validates state file and audit log contents
  4. Validate: All healing actions produce expected outcomes. No false positives on healthy issues. State file matches reality.
  5. Success:
     - Stale detection works for all 3 label types `[ref: SDD/EARS — stale detection]`
     - Fulfilled needs-human auto-closes `[ref: SDD/EARS — needs-human]`
     - Audit trail complete `[ref: SDD/EARS — audit trail]`

- [ ] **T4.2 Circuit Breaker End-to-End Test** `[activity: testing]` `[component: ai-pipeline-template]`

  1. Prime: Read SDD circuit breaker implementation example `[ref: SDD/Implementation Examples/Circuit Breaker]`. Read PRD Feature 7 criteria `[ref: PRD/Feature 7]`.
  2. Test: Create scenario where circuit breaker fires:
     - Create 11+ stale issues that all fail recovery → per-run breaker at 10
     - Create issue that fails 2x → per-issue escalation
     - Verify escalation issue created with summary
     - Verify no further processing after breaker fires
     - On next cycle, verify normal operation resumes
  3. Implement: Test procedure that creates artificial failure conditions and verifies breaker behavior.
  4. Validate: Circuit breaker fires at correct thresholds. Single escalation issue created. Processing stops.
  5. Success:
     - Per-run threshold works `[ref: PRD/AC Feature 7 — criteria 2]`
     - Per-issue 2-failure escalation `[ref: PRD/AC Feature 7 — criteria 1]`
     - Cooldown and reset `[ref: PRD/AC Feature 7 — criteria 3]`

- [ ] **T4.3 Dashboard Integration Test** `[activity: testing]` `[component: chimney]` `[parallel: true]`

  1. Prime: Read PRD Feature 5 criteria `[ref: PRD/Feature 5]`. Read SDD quality requirements for dashboard performance `[ref: SDD/Quality Requirements]`.
  2. Test: With live data from wgmesh:
     - Dashboard loads in <1.5s (cached) / <3s (cold cache)
     - All 6 columns populated correctly from GitHub labels
     - Banner data matches current loop-state.json and costs.json
     - Health colors match issue ages (green <24h, yellow 20-24h, red >24h)
     - Clicking issue card navigates to correct GitHub URL
     - Mobile layout works at 375px viewport
     - Empty state renders when no issues exist
     - Stale data warning appears when cache >4h old
  3. Implement: Manual or automated browser test against chimney.beerpub.dev/pipeline with live data.
  4. Validate: All visual elements correct. Performance targets met. No broken links.
  5. Success:
     - 6 columns with correct data `[ref: PRD/AC Feature 5 — criteria 1]`
     - Health indicators accurate `[ref: PRD/AC Feature 5 — criteria 2, 3]`
     - Banner complete `[ref: PRD/AC Feature 5 — criteria 4]`
     - Mobile responsive `[ref: PRD/AC Feature 5 — criteria 6]`

- [ ] **T4.4 Cross-Component Data Flow Verification** `[activity: testing]`

  1. Prime: Read SDD system context diagram `[ref: SDD/External Interfaces/System Context Diagram]`. Read SDD integration points `[ref: SDD/Integration Points]`.
  2. Test: Full data flow from self-healing → state files → dashboard:
     - Self-healing runs → updates pipeline-health-state.json → PR created → merged
     - Dashboard reads updated pipeline-health-state.json → banner shows latest "Last healed" time
     - Self-healing toggles label on issue → dashboard reflects issue in new column on next cache refresh
     - Observation loop reads pipeline-health-state.json → can consume health data
  3. Implement: Run self-healing workflow, wait for PR merge, then verify dashboard reflects changes. Check end-to-end data propagation.
  4. Validate: Data flows correctly across all components. No stale state inconsistencies. Timing acceptable (15-min cache max delay).
  5. Success:
     - State changes propagate from self-healing to dashboard `[ref: SDD/EARS — audit commit]`
     - Observation loop can read health state `[ref: SDD/Building Block View]`

- [ ] **T4.5 Security and Safety Validation** `[activity: security]`

  1. Prime: Read SDD security patterns `[ref: SDD/Cross-Cutting Concepts/System-Wide Patterns]`. Read SDD risks `[ref: SDD/Risks and Technical Debt]`.
  2. Test:
     - PUSH_TOKEN permissions are minimal (no admin, no delete)
     - Content sanitization runs before every issue creation (grep for `sanitise.sh` calls)
     - Dashboard does not expose assessment narratives, blockers, or strategy
     - `manual-only` label correctly exempts issues from self-healing
     - Rate limit checking works (verify `X-RateLimit-Remaining` check exists)
     - No secrets in state files or audit log (run sanitise.sh on committed files)
  3. Implement: Code review + manual verification of security constraints.
  4. Validate: All security checks pass. No sensitive data exposure.
  5. Success: Security requirements met `[ref: SDD/Quality Requirements/Security]`

- [ ] **T4.6 Performance Baseline** `[activity: performance]` `[parallel: true]`

  1. Prime: Read SDD quality requirements `[ref: SDD/Quality Requirements]`. Read PRD success metrics `[ref: PRD/Success Metrics]`.
  2. Test:
     - Self-healing workflow completes in <5 minutes (measure 3 consecutive runs)
     - API calls per run <100 (count from workflow logs)
     - Dashboard page load <1.5s cached, <3s cold (measure with browser DevTools)
     - Self-healing run success rate >99% over first week (verify no failed runs)
  3. Implement: Collect metrics from first week of operation. Log timing data.
  4. Validate: All performance targets met or within acceptable range.
  5. Success:
     - Self-healing <5 min `[ref: SDD/Quality Requirements/Performance]`
     - Dashboard <1.5s `[ref: SDD/Quality Requirements/Performance]`
     - API budget within limits `[ref: SDD/Constraints/CON-3]`

- [ ] **T4.7 Final Specification Compliance** `[activity: validate]`

  - Complete PRD acceptance criteria matrix:

    | PRD Feature | Criteria Count | Tasks Covering | Status |
    |------------|---------------|----------------|--------|
    | Feature 1: Stale Triage | 3 | T2.1, T4.1 | ⬜ |
    | Feature 2: Stale Copilot | 3 | T2.2, T4.1 | ⬜ |
    | Feature 3: Stale Build | 3 | T2.3, T4.1 | ⬜ |
    | Feature 4: Needs-Human Close | 3 | T2.4, T4.1 | ⬜ |
    | Feature 5: Dashboard | 6 | T3.2-T3.5, T4.3 | ⬜ |
    | Feature 6: Audit Trail | 3 | T2.1-T2.4, T4.1 | ⬜ |
    | Feature 7: Circuit Breaker | 3 | T2.6, T4.2 | ⬜ |
    | Feature 8: Banner Activity | 2 | T3.3 | ⬜ |
    | Feature 9: Empty/Error States | 3 | T3.6, T4.3 | ⬜ |
    | Feature 10: Funnel Signals | 2 | T2.5 | ⬜ |
    | Feature 11: Health History | 1 | Deferred (Could Have) | ⬜ |

  - Verify all SDD EARS acceptance criteria satisfied
  - Verify no deviations from spec without documented rationale
  - Update spec README.md: phase → Ready, plan status → completed
