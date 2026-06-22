# Capability-acquisition ladder — the box grows its own abilities, gated by co-founder consent

**Date:** 2026-06-22 · **Scope:** Deep — product · **Status:** ready for `/ce-plan`
**Origin:** operator — "I expect a proper plan/suggestion grounded on research, strategy,
pros/cons … then I decide; if something is not ok I comment and the LLM revisits, iterating"
→ "if it cannot research/lacks a feature, can it build it? if not, rent a human?" → target
**"1 & 4, but co-founders must agree on the proposal."**
**Builds on:** the Quackback decision layer (`project_quackback_decision_layer`).

## Outcome

The autonomous company stops being capped by the capabilities it shipped with. When the box
hits a gap it cannot directly satisfy, it **climbs a ladder** rather than just punting to a
human:

1. **Do it** — already capable → acts (today's build lane).
2. **Build it** — lacks a tool but can code it → ships the tool *(self-extension)*, then uses it.
3. **Rent a human** — can't build it (needs a real-world act, capital, a signature) → delegates
   to a human.
4. **Escalate** — can't acquire it at all → surfaces to the founders.

The brake on this power is **co-founder consent**: any rung past "do it" requires the box to
post a **researched proposal** to the co-founder board and reach a **quorum of approve-votes**
before it executes. The box proposes; the co-founders decide; only then does it act. The first
thing it proves is **self-build** — it proposes *"add web research to my own pipeline,"* the
co-founders agree, and it ships that capability into itself.

This makes the company *self-extending under consent* — the highest-leverage primitive on the
roadmap and the one with the largest blast radius, which is why the gate is the heart of it.

## The decision/proposal lane (the mechanism that makes the gate real)

A new lane, distinct from the build lane. KTD9 holds throughout: **the box never sets a
decision status** — it drives body, comments, tags, votes-reading only; co-founders drive status.

1. **Trigger.** The box hits a capability gap mid-work, OR a co-founder posts a decision ask
   (a `needs-human` "decide X"). Either becomes a proposal task.
2. **Research.** The box gathers grounding with the web-research tool — competitor/market data,
   prior art — plus internal context (STRATEGY.md, KPIs, the repo). The proposal cites sources.
3. **Propose.** It writes a structured proposal as a **discussion post**: recommendation, the
   options considered, **pros / cons**, **upsides / downsides**, **ROI / cost**, and — when the
   ask is a capability gap — **which rung** it picked and what executing it costs.
4. **Iterate.** Co-founders comment. The box **reads the comments**, distinguishes a co-founder
   comment from its own (author / principal id), and on a new co-founder comment **revises** the
   proposal and reposts. Loop-guarded: it never reacts to its own comments; it tracks a
   last-processed-comment marker; it stops at a max-iteration cap.
5. **Agree.** When the proposal reaches its **approval threshold**, the box opens a clean
   **final proposal post** — the decision record — and retires the discussion post. The
   threshold is a **risk-tiered config policy**, not a fixed quorum, because the team is small
   (currently **2 co-founders**, where a flat quorum is degenerate): **routine** proposals need
   **1** approve-vote (either co-founder); **dangerous** ones (self-modify the pipeline, spend
   over a configured €X, rent a stranger) need **all current co-founders** (= both, at N=2).
   The policy is expressed relative to the *current* co-founder count, so it scales (1 / majority
   / all) as the team grows without redesign. The private board means every voter is a
   co-founder, so vote count is a sound proxy for the count side of the threshold.
6. **Execute.** The box performs the agreed rung (self-build, or — deferred — rent-a-human, or the
   approved product/business action).

## The rungs

### Rung 2 — Build it (self-extension)
The box files the missing capability as a build item **targeting `ai-pipeline-template` (itself)**
and runs its existing spec→impl→PR→judge→merge lane against it. **First proof target: the
web-research tool** — and note the recursion: the box's first self-build is the very capability
its proposals need, so once it lands, the decision lane gets its grounding for free.

**Brakes (all required before self-build is enabled):**
- Front gate: the proposal + co-founder quorum (above).
- Impl gate: the existing impl-judge.
- Revertibility: the change lands as a PR (reviewable, revert-able).
- **Deploy safety:** a self-edit that breaks the pipeline must not brick the loop — the
  self-build path needs a deploy health-gate + automatic rollback (a bad self-merge reverts the
  box to the last-good revision instead of leaving it dead). This is the one brake the current
  product-build lane does not yet need.

### Rung 3 — Rent a human (DEFERRED — design the slot, do not build)
The proposal format reserves a "hire a human" option (task, who, cost), but the execution
infrastructure — payment rails, a contractor/marketplace integration, quality control, and a
hard **budget guard** so the box cannot overspend — is out of scope for v1. Today's `needs-human`
lane already *is* rung-3-to-the-founders; rung-3-to-strangers is a later build.

### Rungs 1 & 4 — existing
Do-it is the current build lane. Escalate is the current `needs-human` surface.

## Scope boundaries

**In (v1):** the ladder *policy*; the decision/proposal lane (research → propose → comment-iterate
→ quorum → final-post → execute); the web-research tool (itself the first self-build); rung-2
self-build with its safety brakes; quorum-vote reading.

**Explicitly out / deferred:**
- **Rung 3 rental execution** — payment, marketplace, QC, budget guard. Slot designed, not built.
- **Public surfaces** — the board stays private/internal (decision-layer KTD9).
- **Self-build of arbitrary scope** — v1 proves it on a contained, reversible tool (web research);
  letting the box rewrite its own core control loop is a later, separately-gated step.
- **Autonomous spend** beyond what a single rung's approved cost covers — no standing budget.

## Success criteria

- A co-founter "decide X" post yields a box-authored proposal in the discussion post containing
  recommendation + options + pros/cons + upsides/downsides + ROI, with cited sources.
- A co-founder comment causes the box to post a revised proposal; the box never iterates on its
  own comment and stops at the cap.
- A proposal that reaches the vote quorum produces a final proposal post and a retired discussion
  post, and triggers execution of exactly the agreed rung.
- The box ships its own web-research tool into `ai-pipeline-template` via a quorum-approved
  self-build, and a later proposal demonstrably uses it.
- A self-build that fails the deploy health-gate rolls the box back to the last-good revision (no
  bricked loop).

## Open questions (for planning)

- **Vote-quorum API — VERIFY.** Does Quackback expose vote *count* and ideally *voter principal
  ids* per post via REST with the `qb_` key? Quorum needs the count; co-founder-attribution needs
  the ids. If only count is exposed, the private-board assumption (all voters are co-founders)
  carries it for v1. Probe the live instance (mirrors the cutover VERIFY discipline).
- **Comment read API — VERIFY.** `QuackbackClient` has `comment()` (write) but no read. Confirm
  `GET /posts/{id}/comments` (or equivalent) returns comments with an author/principal field so
  the box can distinguish co-founder comments from its own and set the processed marker.
- **Threshold policy values.** Risk-tiered (routine = 1, dangerous = all current co-founders),
  expressed relative to current co-founder count — but the concrete values are config: the €X
  spend line that flips a proposal to "dangerous," which rungs/actions count as dangerous, and
  the named co-founder principal set. Not derivable from code. **N=2 caveat:** "dangerous = all"
  means unanimous today, so one unavailable founder stalls a dangerous proposal — decide whether
  that's acceptable (it is the *point* for self-mod/spend) or needs a timeout/override.
- **Closing the discussion post.** KTD9 blocks the box from setting `Cancelled`. It must instead
  `delete_post` the discussion post or tag it `superseded` — decide which (delete loses the
  thread; tag keeps it but clutters).
- **Self-build target boundary.** Which parts of `ai-pipeline-template` may a self-build touch in
  v1 (tools/recipes/extensions = yes; the control loop / safety gates = no)? A guardrail the plan
  must encode.
- **Where the proposal/research runs.** A new box control-loop module (aligns with box-native /
  actions=CI-CD-only) vs a Goose recipe like observation. The web-research tool must attach to
  whichever runs it.

## Dependencies / assumptions

- Quackback instance live, box holds a working `qb_` key with `read/write:feedback`
  (and the all-scopes key already covers comments/votes reads). **Vote + comment read endpoints
  are unverified** (see Open Questions) — both are load-bearing and must be confirmed before the
  lane is built.
- The box's existing build lane (spec→impl→PR→judge→merge→deploy) works and can be pointed at a
  second target repo (`ai-pipeline-template`) — the cloudroof second-instance precedent shows a
  second TARGET_REPO is feasible.
- **The two dangerous powers are self-modification and spend.** Every design decision defers to:
  consent (quorum) before action, revertibility after it, and no unbounded budget.

## Approach

**Sequence by risk, prove the gate before the power.**
1. **Decision lane, read-only-execution first** — research → propose → comment-iterate → quorum →
   final post, where "execute" is initially just *producing the decided artifact* (no self-mod, no
   spend). This ships the whole consent loop with zero blast radius.
2. **Web research as the first self-build** — once the lane works, the box's first quorum-approved
   *executing* proposal is "add web research to my recipe," with the rung-2 deploy brakes in place.
   Proving rung 2 on the very tool the lane wants is the tightest possible first loop.
3. **Rung 3 slot** — carry the "rent a human" option in the proposal schema; build its execution
   later behind a budget guard.

Net-new, not extend: this is a new lane + a new policy, though it reuses the build lane,
the judge, the board, and the deploy path as substrate.
