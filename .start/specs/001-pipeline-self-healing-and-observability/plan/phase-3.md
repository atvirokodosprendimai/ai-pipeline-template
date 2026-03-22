---
title: "Phase 3: Pipeline Dashboard"
status: pending
version: "1.0"
phase: 3
---

# Phase 3: Pipeline Dashboard

## Phase Context

**GATE**: Read all referenced files before starting this phase.

**Specification References**:
- `[ref: SDD/Cross-Cutting Concepts/User Interface & UX]` — Dashboard layout, wireframes, interaction design
- `[ref: SDD/Building Block View/Directory Map]` — chimney component structure
- `[ref: SDD/Integration Points]` — chimney-to-GitHub API data flow
- `[ref: PRD/Feature 5]` — Dashboard acceptance criteria (6 criteria)
- `[ref: PRD/Feature 8]` — Self-healing banner display
- `[ref: PRD/Feature 9]` — Empty and error states
- `[ref: PRD/Detailed Feature Specifications/Pipeline Dashboard]` — Business rules, edge cases, user flow

**Key Decisions**:
- ADR-4: Hardcoded thresholds (24h yellow, 48h red)
- ADR-5: GitHub API direct with 15-min cache
- Public dashboard, no auth, filtered data (no assessment narratives)
- Three-zone layout: Banner → Alert Zone → Kanban
- Mobile: swipeable carousel with 48px+ touch targets
- WCAG 2.1 AA compliance

**Dependencies**:
- Phase 1 complete — state files exist for banner data
- Phase 2 complete — pipeline-health-state.json has self-healing activity data for "Last healed" banner

---

## Tasks

Implements the pipeline dashboard at chimney.beerpub.dev/pipeline. After this phase, the founder can view pipeline state, health indicators, and self-healing activity from any device.

- [ ] **T3.1 GitHub Data Client with Caching** `[activity: backend-api]` `[component: chimney]`

  1. Prime: Read SDD Integration Points for chimney-to-GitHub API calls `[ref: SDD/Integration Points]`. Read chimney's existing codebase to understand its GitHub integration patterns and technology stack.
  2. Test: Client fetches open issues from wgmesh grouped by label; Client reads `loop-state.json`, `costs.json`, `pipeline-health-state.json` from repo contents API; Cache returns stale data within 15-min TTL; Cache invalidates after 15 minutes; Rate limit headers checked before requests
  3. Implement: Create GitHub data client in chimney that:
     - Fetches open issues by label (`needs-triage`, `copilot-triaging`, `approved-for-build`, `goose-implementation`, `needs-review`)
     - Fetches open PRs with `spec:` title prefix
     - Reads state files via GitHub contents API (loop-state.json, costs.json, pipeline-health-state.json)
     - Caches all responses with 15-min TTL
     - Checks `X-RateLimit-Remaining` and warns if <100
  4. Validate: Data correctly grouped by pipeline stage. Cache TTL works. Rate limit protection functional.
  5. Success:
     - Issues grouped into 6 columns `[ref: PRD/AC Feature 5 — criteria 1]`
     - Data cached with 15-min TTL `[ref: SDD/ADR-5]`

- [ ] **T3.2 Pipeline Kanban Component** `[activity: frontend-ui]` `[component: chimney]`

  1. Prime: Read SDD UI wireframes for desktop and mobile layouts `[ref: SDD/Cross-Cutting Concepts/UI Visualization Guide]`. Read PRD business rules for column mapping `[ref: PRD/Detailed Feature Specifications/Pipeline Dashboard/Business Rules]`.
  2. Test: 6 columns render with correct headers (Created, Triaging, Spec PR, Approved, Implementing, Merged); Issue cards display number, title (truncated at ~40 chars), age, health indicator; Cards are clickable → open GitHub issue in new tab; Column headers show issue count; Empty columns show placeholder text
  3. Implement: Create Kanban component with:
     - 6-column layout matching label state machine (Rule 1)
     - Issue cards with: `#number`, truncated title, relative age ("6h ago"), health badge
     - Health badges: 🟢 <24h, 🟡 20-24h, 🔴 >24h (Rule 2)
     - Color + symbol for accessibility (Rule 3)
     - Click handler → `window.open(githubUrl, '_blank')`
     - Empty column placeholder: "No issues at this stage" (Rule 5)
  4. Validate: All 6 columns render. Health colors correct for various ages. Click navigation works. Empty state shows placeholder.
  5. Success:
     - Issues in 6 Kanban columns `[ref: PRD/AC Feature 5 — criteria 1]`
     - Red indicator for >24h `[ref: PRD/AC Feature 5 — criteria 2]`
     - Yellow indicator for 20-24h `[ref: PRD/AC Feature 5 — criteria 3]`
     - Click opens GitHub `[ref: PRD/AC Feature 5 — criteria 5]`

- [ ] **T3.3 Pipeline Banner Component** `[activity: frontend-ui]` `[component: chimney]` `[parallel: true]`

  1. Prime: Read SDD banner wireframe `[ref: SDD/Cross-Cutting Concepts/UI Visualization Guide]`. Read PRD Feature 8 for self-healing display `[ref: PRD/Feature 8]`.
  2. Test: Banner shows funnel stage name from loop-state.json; Banner shows runway months from costs.json; Banner shows "Last healed: Xh ago, fixed N stale issues" from pipeline-health-state.json; "Last healed" text links to self-healing log view; If self-healing never ran, shows "Self-healing: not yet active"
  3. Implement: Create banner component that:
     - Reads funnel stage from loop-state.json (`stage_name`)
     - Reads runway from costs.json (`runway.months_remaining`)
     - Reads last check from pipeline-health-state.json (`last_check`, `last_run_summary.actions_taken`)
     - Computes relative time ("2h ago")
     - "Last healed" is clickable (links to audit log or separate log view)
  4. Validate: All three data sources render correctly. Relative time updates. Fallback text for missing data.
  5. Success:
     - Funnel stage + runway + last healed in banner `[ref: PRD/AC Feature 5 — criteria 4]`
     - Self-healing activity visible `[ref: PRD/AC Feature 8 — criteria 1, 2]`

- [ ] **T3.4 Alert Zone Component** `[activity: frontend-ui]` `[component: chimney]` `[parallel: true]`

  1. Prime: Read UX research for three-zone layout. Alert zone shows only stale (yellow/red) issues.
  2. Test: Given 2 stale issues (1 red, 1 yellow), alert zone renders both with health indicators; Given no stale issues, alert zone is hidden (takes zero vertical space); Alert zone issues are clickable → GitHub
  3. Implement: Create alert zone component that:
     - Filters all issues for age >20h (yellow threshold)
     - Renders as horizontal bar above Kanban
     - Shows: health badge + issue number + title + age
     - Conditionally hidden when no stale issues
  4. Validate: Alert zone appears/disappears correctly. Issue links work. No stale issues = clean dashboard.
  5. Success: Stale issues prominently visible above Kanban `[ref: PRD/Detailed Feature Specifications/Pipeline Dashboard]`

- [ ] **T3.5 Mobile Responsive Layout** `[activity: frontend-ui]` `[component: chimney]`

  1. Prime: Read SDD mobile wireframe `[ref: SDD/Cross-Cutting Concepts/UI Visualization Guide]`. Read PRD Feature 5 criteria 6 for mobile `[ref: PRD/AC Feature 5 — criteria 6]`.
  2. Test: At <480px, columns display as swipeable carousel; Touch targets ≥48px; Banner compresses to single-line summary; Alert zone stacks vertically; Pagination dots show current column position
  3. Implement: Add responsive CSS/JS for:
     - Mobile carousel (CSS `overflow-x: scroll` + `scroll-snap-type`) or JS swipe library
     - Compressed banner at narrow viewport
     - Vertical alert zone stacking
     - 48px minimum touch targets on all interactive elements
  4. Validate: Test at 375px (iPhone SE), 390px (iPhone 14), 768px (iPad). All elements usable. No horizontal overflow except carousel.
  5. Success: Mobile carousel with 48px+ targets `[ref: PRD/AC Feature 5 — criteria 6]`

- [ ] **T3.6 Empty and Error States** `[activity: frontend-ui]` `[component: chimney]`

  1. Prime: Read PRD Feature 9 for empty/error state acceptance criteria `[ref: PRD/Feature 9]`. Read SDD Error Handling `[ref: SDD/Runtime View/Error Handling]`.
  2. Test: Given no open issues, dashboard shows "Pipeline is empty. Create an issue to get started." with link; Given all issues healthy, alert zone shows success indicator; Given data >4h stale, warning banner shows "Data stale. Last sync: Xh ago"; Given GitHub API 403, cached data shown with "API rate limited" warning
  3. Implement: Add conditional rendering for:
     - Empty pipeline → issue template link
     - All healthy → success indicator in alert zone
     - Stale data (cache age >4h) → yellow warning bar with countdown
     - API error → cached data + error notice
  4. Validate: All 4 states render correctly. Warnings are clear and actionable.
  5. Success:
     - Empty state with CTA `[ref: PRD/AC Feature 9 — criteria 1]`
     - All-healthy indicator `[ref: PRD/AC Feature 9 — criteria 2]`
     - Stale data warning `[ref: PRD/AC Feature 9 — criteria 3]`

- [ ] **T3.7 Accessibility Compliance** `[activity: frontend-ui]` `[component: chimney]`

  1. Prime: Read SDD accessibility requirements `[ref: SDD/Cross-Cutting Concepts/User Interface & UX/Interaction Design]`.
  2. Test: Color contrast ≥4.5:1 on all text; Health indicators use color + symbol (not color alone); Keyboard navigation: Tab through columns → cards; Screen reader announces: "Column: Created, 8 issues, 6 green, 2 yellow"; Focus indicators visible on all interactive elements; No auto-refresh (manual or configurable only)
  3. Implement: Add ARIA labels, role attributes, keyboard handlers, focus styles. Ensure health badges include both emoji and text label.
  4. Validate: Run with VoiceOver/NVDA. Tab through all elements. Check contrast with DevTools.
  5. Success: WCAG 2.1 AA compliance `[ref: SDD/Quality Requirements]`

- [ ] **T3.8 Phase Validation** `[activity: validate]`

  - Deploy chimney with /pipeline route. Verify:
    - Dashboard loads at chimney.beerpub.dev/pipeline
    - All 6 columns render with live GitHub data
    - Banner shows correct funnel stage, runway, and last healed time
    - Alert zone shows stale issues (or hides when none)
    - Mobile layout works on phone viewport
    - Empty state displays when no issues exist
    - Accessibility audit passes (keyboard nav, screen reader, contrast)
    - Page load <1.5s with cached data
