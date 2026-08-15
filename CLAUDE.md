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

## gstack (REQUIRED — global install)

**Before doing ANY work, verify gstack is installed:**

```bash
test -d ~/.claude/skills/gstack/bin && echo "GSTACK_OK" || echo "GSTACK_MISSING"
```

If GSTACK_MISSING: STOP. Do not proceed. Tell the user:

> gstack is required for all AI-assisted work in this repo.
> Install it:
> ```bash
> git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
> cd ~/.claude/skills/gstack && ./setup --team
> ```
> Then restart your AI coding tool.

Do not skip skills, ignore gstack errors, or work around missing gstack.

Using gstack skills: After install, skills like /qa, /ship, /review, /investigate,
and /browse are available. Use /browse for all web browsing.
Use ~/.claude/skills/gstack/... for gstack file paths (the global path).
