# AI Pipeline Template

Drop-in AI pipeline: **GitHub Copilot** writes specs, **humans** approve, **Goose** builds code. Works with any language.

![Pipeline Flow](docs/pipeline-flow.svg)

## How It Works

| Phase | Actor | What Happens |
|-------|-------|-------------|
| 1. Issue | User | Files a bug report or feature request via issue template |
| 2. Triage | Copilot | Analyzes the issue, writes a specification document, opens a spec PR |
| 3. Approval | Human | Reviews the spec PR. Comments `/approve`, `/wont-do`, or `/needs-info` |
| 4. Build | Goose | Reads the approved spec, implements the code, opens a draft PR |
| 5. Review | Human | Reviews the implementation PR, merges to main |

## Quick Start

### 1. Create your repo from this template

Click **[Use this template](../../generate)** on GitHub, or:

```bash
gh repo create my-project --template atvirokodosprendimai/ai-pipeline-template --public --clone
cd my-project
```

### 2. Run the setup script

```bash
./init.sh
```

The script will ask for your project name, language, build commands, and LLM provider. It loads sensible defaults for Go, Node.js, Python, and Rust - or you can choose "other" for any language.

### 3. Commit and push

```bash
git add -A && git commit -m "Initialize AI pipeline" && git push
```

### 4. Configure GitHub

1. **Add your LLM API key** as a repository secret (Settings > Secrets > Actions)
2. **Enable Copilot coding agent** (Settings > Copilot > Coding agent)
3. **Run the "Sync Labels" workflow** from the Actions tab to create pipeline labels
4. **(Optional) Set up a project board** — see [CONTRIBUTING.md](CONTRIBUTING.md#board-setup) for instructions

## Supported Languages

| Language | Build | Test | Lint | Format |
|----------|-------|------|------|--------|
| Go | `go build ./...` | `go test ./...` | `go vet ./...` | `gofmt -w .` |
| Node.js | `npm run build` | `npm test` | `npm run lint` | `prettier --write .` |
| Python | `python -m build` | `pytest` | `ruff check .` | `ruff format .` |
| Rust | `cargo build` | `cargo test` | `cargo clippy` | `cargo fmt` |
| Other | *(you provide)* | *(you provide)* | *(you provide)* | *(you provide)* |

All defaults can be overridden during `init.sh` setup.

## Slash Commands

Comment these on **spec PRs** to control the pipeline:

| Command | Effect |
|---------|--------|
| `/approve` | Approves the spec and triggers Goose to implement |
| `/wont-do` | Rejects the spec and closes the PR |
| `/needs-info` | Pauses and asks the issue reporter for more details |

Only users with **write access** to the repository can use these commands.

## File Manifest

```
.github/
  copilot-instructions.md     # Copilot behavior config (edit for your project)
  labels.yml                  # Pipeline label definitions
  ISSUE_TEMPLATE/
    bug_report.yml            # Bug report form
    feature_request.yml       # Feature request form
  workflows/
    copilot-triage.yml        # Triggers Copilot on needs-triage label
    approve-build.yml         # Handles /approve, /wont-do, /needs-info
    goose-build.yml           # Installs toolchain + Goose, runs implementation
    sync-labels.yml           # Creates/syncs pipeline labels
    board-sync.yml            # Auto-moves project board items by label
.goosehints                   # Goose project context (edit for your project)
CONTRIBUTING.md               # Pipeline guide for contributors
specs/                        # Spec documents go here (auto-created by Copilot)
docs/
  pipeline-flow.d2            # Pipeline diagram source (D2 language)
  pipeline-flow.svg           # Rendered pipeline diagram
```

## Prerequisites

- **GitHub Copilot** with coding agent enabled ([docs](https://docs.github.com/en/copilot/using-github-copilot/using-copilot-coding-agent-to-work-on-tasks))
- **LLM API key** for Goose (Google Gemini free tier works, or OpenAI/Anthropic)
- A GitHub repository (public or private)

## LLM Providers

Goose supports multiple LLM providers. The setup script includes presets for:

| Provider | Default Model | Secret Name |
|----------|--------------|-------------|
| Google | `gemini-2.0-flash` (free tier) | `GOOGLE_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Anthropic | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |

## Customization

After running `init.sh`, you should edit these files for your project:

- **`.github/copilot-instructions.md`** - Add your project structure, code style, security guidelines
- **`.goosehints`** - Add your architecture, key dependencies, important files
- **`.github/ISSUE_TEMPLATE/*.yml`** - Customize the component dropdown for your project

## FAQ

**Q: Can I use this with a monorepo?**
A: Yes. Edit `.goosehints` and `copilot-instructions.md` to describe your monorepo structure. You may want to adjust the build/test commands in `goose-build.yml` to target specific packages.

**Q: What if Goose produces bad code?**
A: The implementation PR is always created as a **draft**. Review it like any other PR. You can request changes, close it, or manually fix and merge.

**Q: Can I change the LLM provider later?**
A: Yes. Edit the `env:` section at the top of `.github/workflows/goose-build.yml` and update your repository secrets.

**Q: What if I don't use GitHub Copilot?**
A: The triage phase requires Copilot coding agent. Without it, you can still manually write specs in `specs/` and use `/approve` to trigger Goose.

**Q: How do I update the pipeline diagram?**
A: Edit `docs/pipeline-flow.d2` and render with: `d2 --theme 200 --layout elk docs/pipeline-flow.d2 docs/pipeline-flow.svg`

## License

Apache-2.0 - see [LICENSE](LICENSE) for details.
