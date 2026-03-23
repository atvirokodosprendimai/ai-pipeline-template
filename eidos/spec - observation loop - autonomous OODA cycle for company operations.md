---
tldr: Autonomous OODA loop that collects signals across repos, calls an LLM to assess company state, and drives the pipeline through issues, closures, and memory updates every 8 hours.
category: core
---

# Observation Loop

## Target

Keep the company moving without human gates. Every 8 hours (or on demand), the loop reads the real state of all repos and infrastructure, hands that picture to an LLM acting as operating brain, and turns the LLM's judgement into concrete GitHub artifacts: new issues routed to the right function, stale issues and PRs closed, human escalations filed, and the memory updated so the next run inherits context. The loop is the only thing that decides what the company does next.

## Behaviour

- Runs on a fixed 8-hour cadence (00:00, 08:00, 16:00 UTC) and can be triggered manually or via `repository_dispatch` for event-driven signals such as payment webhooks or alerts. {>> the cron and `repository_dispatch` type `company-signal` are both present; webhook-driven signals feed the same assess/act path as scheduled runs}

- Collects five distinct signal streams before calling the LLM: GitHub metadata (one primary repo at full depth, secondary repos at lightweight depth), infrastructure health (HTTP probes against configured endpoints), contribution signals (recent git authors, bot commit count, unreciprocated contributor count), a product codebase summary (CLAUDE.md from the primary product repo), and shared memory (semantic MEMORY.md plus recent episodic entries budget-capped at 6 KB). {>> separating primary from secondary GitHub collection preserves Search API quota — primary gets label counts via search, secondaries get only REST stats}

- The primary product repo receives full collection including function-label issue counts (`fn:dev`, `fn:ops`, `fn:gtm`, `fn:billing`, `fn:support`, `fn:legal`, `needs-human`); secondary repos receive only stars, forks, open issue count, and open PR count. This asymmetry is intentional: the primary repo drives the development pipeline.

- The LLM is called with a structured JSON snapshot merged from all signals plus the open board (all open issues and PRs, and recently closed issues for dedup) and the 3 most recent assessment markdown files for continuity. The call is routed through an OpenAI-compatible proxy (OpenRouter). If the API key is absent or the call fails, the loop emits a well-formed stub assessment that names the failure as a blocker and continues all downstream steps rather than halting.

- The LLM must return valid JSON conforming to a fixed schema: `timestamp`, `funnel_stage` (0–5), `stage_name`, `runway`, `assessment` narrative, `blockers`, `top_actions`, `issues_to_create`, `issues_to_close`, `prs_to_close`, `contributions`, `reciprocation_proposals`, `needs_human`. Every field is optional with safe defaults so partial responses do not abort the run.

- Issues are created in the primary product repo only. Before creating each issue the loop performs fuzzy dedup against open AND recently closed issue titles: it extracts up to 5 meaningful keywords (a fixed stop-word list removes common verbs and prepositions), then requires at least 2 keyword hits against any existing title before treating it as a duplicate. This prevents re-creating work that was completed and closed. {>> checking closed titles as well as open ones was added after an RCA where the LLM re-created already-implemented features}

- Issues identified for closure are closed by number with an automated comment explaining the reason. PRs identified for closure are closed with the same mechanism but support cross-repo targets by accepting a `repo` field alongside the `number`.

- `needs_human` entries produce issues labeled `needs-human` in the primary repo, subject to the same fuzzy dedup as normal issues. The `needs_human` label is reserved exclusively for things that cannot be contracted over the internet — physical presence, wet signatures, irreversible decisions with no undo path.

- All content written to the public repo (assessment markdown, episodic memory, issue titles and bodies) passes through `sanitise.sh` before commit. Sanitisation fails hard (non-zero exit, issue skipped) if any pattern matching API keys, private keys, or credential-style secrets is detected. Email addresses that are not known bot addresses trigger a warning but do not block the commit. {>> the sanitiser is fail-safe: unknown content is blocked, not silently passed}

- Stale `needs-triage` issues older than 24 hours are re-triggered at the end of every run by removing then re-adding the label, which re-fires the triage workflow. This catches silent failures in the triage automation without requiring a separate monitoring job.

- Assessment state is written to three places: `company/loop-history/YYYYMMDD-assessment.md` (human-readable markdown for the public record), `company/loop-state.json` (machine state: last run timestamp, current funnel stage, run count), and `memory/episodic/YYYYMMDD-HHMM-loop-daily-assessment.md` (structured episodic entry with YAML frontmatter for the memory subsystem). {>> the three destinations serve different consumers: humans reading the repo, the loop's own state machine, and other agents reading episodic memory}

- State changes are committed to a dated branch (`loop/assessment-YYYY-MM-DD-<run-id>`) and submitted as a PR against `main`. PR merge is handled by a separate bot-pr-review-merge workflow; the loop does not self-merge. Concurrent loop runs are serialised — the `concurrency` group `observation-loop` with `cancel-in-progress: false` queues rather than cancels overlapping runs.

- The loop tracks a funnel stage from 0 (Foundation) to 5 (Revenue). Stage assessment is performed by the LLM from real signals, not hardcoded. The stage is persisted in `loop-state.json` and fed back into every subsequent run so the LLM has a prior to reason from.

- Runway is tracked and reported every run: `available_capital / monthly_burn`. If `months_remaining` falls below 3 the LLM enters survival mode (no new spend, revenue-only focus). Capital figures live in `costs.json` and are set by a human; the loop computes the ratio. {>> costs.json holds only aggregate categories, never raw invoices or provider credentials}

- Contributions from any entity (human, AI agent, open-source library, infrastructure provider) are logged each run in the assessment's `contributions` field. Unreciprocated contributors are surfaced via the `reciprocation_proposals` field when revenue allows action. The contribution ledger (count of unreciprocated contributors) is tracked in `company/contributors.json` and fed into the signal snapshot.

- The public/private boundary is enforced at two levels: the system prompt instructs the LLM what to omit (credentials, customer PII, exact revenue figures), and `sanitise.sh` enforces it mechanically on anything the LLM writes before it is committed. The boundary is non-negotiable because assessments are committed to a public repo.

- The product codebase summary (from CLAUDE.md) is injected into every LLM call to prevent hallucination of missing features. The LLM is explicitly instructed to close issues for features already present in the codebase and never to create issues for them. {>> this was added after RCA issue #458 where the LLM created spec issues for features that were fully implemented}

- Every `fn:dev` action in `top_actions` must have a corresponding entry in `issues_to_create` or an existing open issue. `top_actions` is a human-readable report; `issues_to_create` is the only thing that actually drives the pipeline. An action without a matching issue is inert.

## Design

**OODA as a pipeline.** Observe, Orient, Decide, Act maps directly to the workflow steps: collect signals → merge snapshot → call LLM → execute outputs. Each phase is a distinct step with clear inputs and outputs. Phases are not skippable; even on LLM failure, the Act phase runs with stub outputs.

**Tiered collection.** Not all repos warrant the same API depth. The primary product repo receives full collection including expensive Search API calls for label counts. Secondary repos get only REST repo stats. This keeps the loop within GitHub API rate limits as the organisation grows without needing per-repo configuration.

**Fail-safe degradation.** Every collection step emits a valid JSON error document on failure rather than aborting the run. The LLM call falls back to a well-formed stub that names the failure as a blocker. This means the Act phase always executes — even a partial run produces loop-state and episodic memory updates, maintaining temporal continuity.

**Memory is two-layer.** Semantic memory (MEMORY.md) holds curated, timeless knowledge. Episodic memory (dated markdown files with YAML frontmatter) holds what happened on specific runs. The loop reads both and writes only episodic entries. Semantic memory is curated by humans or separate agents. The 6 KB budget prevents unbounded context growth while ensuring the most recent 5 episodes are always included.

**Dedup is fuzzy and bidirectional.** Exact-match dedup would miss rephrased duplicates; semantic similarity would require an embedding call. Five-keyword fuzzy matching with a 2-hit threshold is a cheap middle ground that works across rephrasing without false positives. Checking closed titles as well as open ones closes the loop on features that were built and closed — the most common source of duplicate issue spam.

**Sanitise before commit, not after.** The sanitise gate runs on content before it touches the git index. An issue that fails sanitisation is skipped and logged as a warning; it does not abort the remaining issues. This means a single bad LLM output line cannot block legitimate issues from being created.

**Issues are the API.** The loop does not call other workflows directly. It writes issues with function labels (`fn:dev`, `fn:ops`, `fn:gtm`, etc.), and label-driven workflows pick them up. This decouples the loop from the downstream pipeline — adding a new function requires only a new label handler, not a change to the loop itself.

**The LLM is the operating brain, not a generator.** The system prompt instructs the LLM to assess based on real signals, not to invent activity. If nothing changed, it should say so. This keeps assessments honest and avoids the common failure mode of AI systems that generate plausible-sounding but fabricated status.

## Interactions

- Depends on GitHub Actions runner environment for secret injection (`PUSH_TOKEN`, `OPENROUTER_API_KEY`)
- Depends on OpenRouter (OpenAI-compatible proxy) for LLM access; model is `anthropic/claude-sonnet-4`
- Depends on `company/health.json` for the list of infrastructure endpoints to probe
- Depends on `company/contributors.json` for the unreciprocated contributor ledger
- Depends on `company/costs.json` for runway calculation inputs (human must set `available_capital`)
- Depends on `company/loop-state.json` for prior funnel stage and run count
- Depends on `memory/MEMORY.md` and `memory/episodic/` for shared memory
- Produces issues and issue closures in the primary product repo (`atvirokodosprendimai/wgmesh`)
- Produces a dated PR against `main` consumed by the bot-pr-review-merge workflow
- Produces episodic memory entries consumed by all agents that read shared memory
- Produces `company/loop-state.json` updates consumed by the next loop run and any subsystem reading funnel stage
- Produces `company/loop-history/*.md` consumed by the next loop run (as recent history context) and by humans reading the repo

Related specs:
- [[spec - pipeline state machine - label driven issue lifecycle]]
- [[spec - self healing - deterministic pipeline recovery]]
- [[spec - infrastructure monitoring - endpoint health and alerting]]
- [[spec - security quality - constitution and enforcement]]

## Mapping

- [[.github/workflows/observation-loop.yml]]
- [[company/scripts/collect-github.sh]]
- [[company/scripts/collect-infra.sh]]
- [[company/scripts/collect-contributions.sh]]
- [[company/scripts/collect-memory.sh]]
- [[company/scripts/sanitise.sh]]
- [[company/system-prompt.md]]
- [[company/loop-state.json]]
- [[company/costs.json]]
- [[company/metrics.json]]
- [[company/loop-history/]]
- [[memory/episodic/]]
