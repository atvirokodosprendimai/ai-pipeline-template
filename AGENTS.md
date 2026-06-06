# AGENTS.md

Canonical entry point for any agent (Codex, Claude, Goose) or human working in this
repo. Other tool-specific files (`CLAUDE.md`, `.goosehints`) point here — edit this
file, not those.

## What this repo is

`ai-pipeline-template` is the **control plane for an autonomous company** that builds,
markets, sells, and operates **wgmesh** (decentralized WireGuard mesh networking with
managed ingress). It is not the product — it is the brain and the pipeline that drives
product repos.

A daily **observation loop** assesses company state and files GitHub issues; those issues
flow through an automated pipeline to shipped code.

## The pipeline

```
Issue → Spec (Copilot) → Review Spec → Build (Goose) → Review Code → Merge
```

Issues are labeled `fn:dev | fn:ops | fn:gtm | fn:billing | fn:support | fn:legal` to
route them. Board columns move automatically from labels — never drag cards. See
`CONTRIBUTING.md` for the maintainer's two review checkpoints (Review Spec, Review Code).

## Authoritative documents (read these before acting)

| File | Role |
|------|------|
| `CONSTITUTION.md` | Governing principles and hard constraints for the autonomous company. |
| `company/system-prompt.md` | The control-loop agent's full operating prompt: funnel stages 0–5, frugality rules, public/private boundary, issue/PR hygiene, output JSON schema. |
| `CONCEPTS.md` | Shared domain vocabulary (glossary). *(seeded in PR #1440)* |
| `CONTRIBUTING.md` | Pipeline stages and human review checkpoints. |
| `STRATEGY.md` | Current product target, approach, metrics, tracks of work. |
| `memory/MEMORY.md` | Curated cross-session learnings (semantic memory). Recent runs in `memory/episodic/` and `company/loop-history/`. |

## Layout

| Path | Contents |
|------|----------|
| `.github/workflows/` | The crons: `observation-loop` (daily LLM assessment), `pipeline-health` ("heal"), `supervisor-rank` (clog ranker), plus spec/build/merge automation and RAH/Polar integrations. |
| `.github/scripts/` | Supervisor-rank pipeline (`snapshot → classify → rank → recommend → publish`) and its `test-*.sh` harnesses. |
| `company/` | Loop state (`loop-state.json`, `pipeline-health-state.json`, `supervisor-rank-state.json`), `system-prompt.md`, `scripts/` (collectors: github/infra/memory/contributions), `loop-history/`. |
| `docs/` | `solutions/` (compounded learnings by category), `brainstorms/`, `plans/`, `pulse-reports/`. |
| `infrastructure/` | Terraform / deploy. |
| `specs/` | Approved specs awaiting build. |

## Build / test / lint

There is no compiled build — this repo is workflows, bash, and docs. Tests are bash
harnesses; run the one nearest your change:

```bash
bash .github/scripts/test-publish.sh        # supervisor-rank publish/dedup
bash .github/scripts/test-rank.sh           # ranking
bash .github/scripts/test-classify.sh       # clog classification
bash .github/scripts/test-assert-state-mutation.sh
bash company/scripts/test-collect-memory.sh
bash company/scripts/test-pr-review-merge.sh
bash company/scripts/test-self-healing-e2e.sh
```

Before any script change is "done": `bash -n <script>` (syntax), run its `test-*.sh`,
and `shellcheck` if available. **Every input-producing script needs a test that exercises
its real (non-dry-run) path** — dry-run-only coverage has shipped bugs here before.

## Behavioral Rules

Bias toward correctness, small diffs, and verified changes.

### Think Before Coding

- State assumptions. If requirements are ambiguous, ask before editing.
- If multiple interpretations exist, present them instead of choosing silently.
- Push back on overcomplicated or speculative work.
- For non-trivial changes, define success criteria and a short plan before implementation.

### Simplicity First

- Implement only what was requested.
- Do not add abstractions for single-use code.
- Do not add configurability, fallback paths, or defensive handling for impossible states.
- If a change grows large, stop and simplify before continuing.

### Surgical Changes

- Touch only files needed for the request.
- Do not refactor, reformat, or clean adjacent code unless required.
- Match existing style, even when a different style would be preferable.
- Remove only unused imports, variables, or functions created by your own change.
- Mention unrelated dead code or issues; do not fix them unless asked.

### Verified Execution

- Convert tasks into verifiable goals: reproduce bugs, add focused tests when useful, then make checks pass.
- For multi-step work, use: `step -> verify: check`.
- Do not claim completion without evidence from tests, lint, type-check, build, runtime output, or source tracing.
- See [Stop the line on defects](#conventions) below — fix a failing check before continuing.

## Conventions

- **Public repo.** Loop assessments are committed and world-readable. Never write secrets,
  customer PII, or exact revenue figures (use aggregates). Full boundary in
  `company/system-prompt.md`.
- **Frugality is survival.** Before any cost: can it be zero? cheap? necessary now?
  A human approves any new recurring spend above zero.
- **State-mutating crons must assert the mutation happened** — a green workflow run does
  not prove state changed. Gate commits/issues on material-change fingerprints, not on
  per-run metadata (`last_run_at`, `run_number`), which always diffs.
- **Stop the line on defects.** Fix a failing check before continuing; understand the root
  cause, don't paper over it.
- Conventional commits (`feat|fix|refactor|docs|test|chore|perf|ci`). Branch off `main`;
  open a PR — `main` requires one review.

## Working memory

`memory/MEMORY.md` is the index of hard-won learnings — consult it before changing a
workflow or script, and add an entry when you learn something non-obvious. Memory is
injected into the `observation-loop` prompt via `company/scripts/collect-memory.sh`; the
pure-bash crons (`pipeline-health`, `supervisor-rank`) make no LLM call and so consume no
memory — keep their logic self-evident.
