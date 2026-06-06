# CLAUDE.md

This project's canonical agent guidance lives in **[AGENTS.md](./AGENTS.md)** — read it
first. It is the single source of truth for repo purpose, the pipeline, authoritative
documents, layout, build/test/lint, and conventions.

Tool-specific notes for Claude Code only:

- The control-loop operating prompt is `company/system-prompt.md` (funnel stages,
  frugality, public/private boundary, output schema). Treat it as ground truth for how the
  autonomous company behaves.
- Curated learnings are in `memory/MEMORY.md`. Consult before changing workflows/scripts;
  add an entry when you learn something non-obvious.
- This is a **public** repo — never commit secrets, PII, or exact revenue figures.
