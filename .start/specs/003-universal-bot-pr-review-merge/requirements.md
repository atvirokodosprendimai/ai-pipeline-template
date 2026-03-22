---
title: "Universal Bot PR Review and Merge"
status: draft
version: "1.0"
---

# Product Requirements Document

## Product Overview

### Vision

Every bot-authored PR gets autonomous review-merge regardless of which workflow created it.

### Problem Statement

Spec 002 wired pr-review-merge.sh into pipeline-health.yml and observation-loop.yml. But PRs created by other workflows (approve-build, copilot-triage, copilot-undraft, spec-validation) or by manual bot invocation don't trigger the review-merge script. Each new workflow requires manual wiring — that doesn't scale and creates gaps.

### Value Proposition

A single event-driven workflow that catches all bot-authored PRs eliminates per-workflow wiring. New workflows get review-merge for free.

## User Personas

Inherited from spec 002. Primary: Pipeline Operator. Secondary: Developer, Human Reviewer.

## Feature Requirements

### Must Have

#### Feature 1: Universal PR Review-Merge Trigger

- **User Story:** As a pipeline operator, I want all bot-authored PRs to be automatically reviewed and merged so that I don't need to wire each workflow individually.
- **Acceptance Criteria:**
  - [ ] Given a PR is opened by an approved bot author, When the `pull_request` event fires, Then pr-review-merge.sh runs against that PR
  - [ ] Given a PR is opened by a human, When the `pull_request` event fires, Then the workflow skips (no action)
  - [ ] Given a PR is opened by an unknown bot, When the `pull_request` event fires, Then the workflow skips (author not in approved list)
  - [ ] Given pr-review-merge.sh is already running inline (e.g., pipeline-health), When the universal workflow also triggers, Then only one instance runs (no double-merge)

#### Feature 2: Deduplication with Inline Callers

- **User Story:** As a pipeline operator, I want the universal workflow to not conflict with workflows that already call pr-review-merge.sh inline.
- **Acceptance Criteria:**
  - [ ] Given pipeline-health.yml already calls pr-review-merge.sh after creating a PR, When the universal workflow triggers on the same PR, Then it detects the PR is already being processed and skips
  - [ ] Given a PR is created by a workflow without inline review-merge, When the universal workflow triggers, Then it runs normally

### Should Have

#### Feature 3: Remove Inline Wiring

- **User Story:** As a pipeline operator, I want to remove the inline pr-review-merge.sh calls from pipeline-health.yml and observation-loop.yml since the universal workflow handles all PRs.
- **Acceptance Criteria:**
  - [ ] Given the universal workflow is active, When pipeline-health creates a PR, Then the universal workflow handles review-merge (not the inline call)
  - [ ] Given inline calls are removed, When the system runs, Then zero duplicate processing occurs

### Won't Have (This Phase)

- Cross-repo PR handling (Phase 3 from spec 002 brainstorm)
- Human-authored PR review

## Success Metrics

- 100% of bot-authored PRs processed by review-merge (zero gaps)
- Zero duplicate processing (no double-merge attempts)
- Zero new per-workflow wiring needed for future workflows

## Constraints

- GitHub Apps (Copilot) don't fire `pull_request_review` events — must use `pull_request` trigger
- PUSH_TOKEN required (ARCH-8)
- Must comply with CONSTITUTION v2.0 (Andon, SEC-*, ARCH-*, QUAL-*)
