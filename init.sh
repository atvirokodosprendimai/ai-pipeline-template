#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════
# AI Pipeline Template - Interactive Setup
# Replaces __PLACEHOLDER__ markers with your project's values,
# then removes itself.
# ══════════════════════════════════════════════════════════════

echo ""
echo "  AI Pipeline Template Setup"
echo "  =========================="
echo ""

# ── Language presets (all languages are equal peers) ──────────

declare -A PRESET_VERSION=(  [go]="1.23"  [node]="20"  [python]="3.12"  [rust]="stable" )
declare -A PRESET_BUILD=(    [go]="go build ./..."  [node]="npm run build"  [python]="python -m build"  [rust]="cargo build" )
declare -A PRESET_TEST=(     [go]="go test ./..."   [node]="npm test"       [python]="pytest"           [rust]="cargo test" )
declare -A PRESET_LINT=(     [go]="go vet ./..."    [node]="npm run lint"   [python]="ruff check ."     [rust]="cargo clippy" )
declare -A PRESET_FMT=(      [go]="gofmt -w ."     [node]="prettier --write ."  [python]="ruff format ."  [rust]="cargo fmt" )
declare -A PRESET_ACTION=(   [go]="actions/setup-go@v5"  [node]="actions/setup-node@v4"  [python]="actions/setup-python@v5"  [rust]="dtolnay/rust-toolchain@stable" )
declare -A PRESET_WITH=(     [go]="go-version"      [node]="node-version"   [python]="python-version"   [rust]="toolchain" )

# ── Provider presets ─────────────────────────────────────────

declare -A PROVIDER_MODEL=(  [google]="gemini-2.0-flash"  [openai]="gpt-4o"  [anthropic]="claude-sonnet-4-20250514" )
declare -A PROVIDER_KEY=(    [google]="GOOGLE_API_KEY"    [openai]="OPENAI_API_KEY"  [anthropic]="ANTHROPIC_API_KEY" )

# ── Helper: prompt with default ──────────────────────────────

prompt() {
  local var_name="$1"
  local prompt_text="$2"
  local default_val="${3:-}"

  if [[ -n "$default_val" ]]; then
    read -rp "  $prompt_text [$default_val]: " input
    eval "$var_name=\"${input:-$default_val}\""
  else
    local input=""
    while [[ -z "$input" ]]; do
      read -rp "  $prompt_text: " input
      if [[ -z "$input" ]]; then
        echo "    (required)"
      fi
    done
    eval "$var_name=\"$input\""
  fi
}

# ── Cross-platform sed ───────────────────────────────────────

if [[ "$(uname)" == "Darwin" ]]; then
  sedi() { sed -i '' "$@"; }
else
  sedi() { sed -i "$@"; }
fi

# ══════════════════════════════════════════════════════════════
# Interactive prompts
# ══════════════════════════════════════════════════════════════

echo "  Project"
echo "  -------"
prompt PROJECT_NAME "Project name"
prompt PROJECT_DESC "Brief description"
echo ""

echo "  Language"
echo "  --------"

# Language selection (required, no default)
LANG_CHOICE=""
while [[ -z "$LANG_CHOICE" ]]; do
  read -rp "  Language [go/node/python/rust/other]: " LANG_CHOICE
  case "$LANG_CHOICE" in
    go|node|python|rust|other) ;;
    *)
      echo "    Choose: go, node, python, rust, or other"
      LANG_CHOICE=""
      ;;
  esac
done

if [[ "$LANG_CHOICE" != "other" ]]; then
  echo "    Loaded ${LANG_CHOICE} presets"
  LANGUAGE="$LANG_CHOICE"
  DEFAULT_VERSION="${PRESET_VERSION[$LANG_CHOICE]}"
  DEFAULT_BUILD="${PRESET_BUILD[$LANG_CHOICE]}"
  DEFAULT_TEST="${PRESET_TEST[$LANG_CHOICE]}"
  DEFAULT_LINT="${PRESET_LINT[$LANG_CHOICE]}"
  DEFAULT_FMT="${PRESET_FMT[$LANG_CHOICE]}"
  DEFAULT_ACTION="${PRESET_ACTION[$LANG_CHOICE]}"
  DEFAULT_WITH="${PRESET_WITH[$LANG_CHOICE]}"
else
  prompt LANGUAGE "Language name (e.g. java, elixir, zig)"
  DEFAULT_VERSION=""
  DEFAULT_BUILD=""
  DEFAULT_TEST=""
  DEFAULT_LINT=""
  DEFAULT_FMT=""
  DEFAULT_ACTION=""
  DEFAULT_WITH=""
fi

prompt LANG_VERSION  "Language version"        "$DEFAULT_VERSION"
prompt BUILD_CMD     "Build command"           "$DEFAULT_BUILD"
prompt TEST_CMD      "Test command"            "$DEFAULT_TEST"
prompt LINT_CMD      "Lint command"            "$DEFAULT_LINT"
prompt FORMAT_CMD    "Format command"          "$DEFAULT_FMT"
prompt SETUP_ACTION  "GH Actions setup action" "$DEFAULT_ACTION"
prompt SETUP_WITH    "Setup action 'with' key" "$DEFAULT_WITH"
echo ""

echo "  LLM Provider (for Goose)"
echo "  ------------------------"

PROVIDER=""
while [[ -z "$PROVIDER" ]]; do
  read -rp "  Provider [google/openai/anthropic/other]: " PROVIDER
  case "$PROVIDER" in
    google|openai|anthropic|other) ;;
    *)
      echo "    Choose: google, openai, anthropic, or other"
      PROVIDER=""
      ;;
  esac
done

if [[ "$PROVIDER" != "other" ]]; then
  DEFAULT_MODEL="${PROVIDER_MODEL[$PROVIDER]}"
  DEFAULT_KEY="${PROVIDER_KEY[$PROVIDER]}"
  GOOSE_PROVIDER="$PROVIDER"
else
  prompt GOOSE_PROVIDER "Provider name"
  DEFAULT_MODEL=""
  DEFAULT_KEY=""
fi

prompt GOOSE_MODEL    "Model name"           "$DEFAULT_MODEL"
prompt API_KEY_SECRET "API key secret name"  "$DEFAULT_KEY"
echo ""

# ══════════════════════════════════════════════════════════════
# Replace placeholders
# ══════════════════════════════════════════════════════════════

echo "  Applying configuration..."

# Escape special characters for sed (forward slashes, ampersands)
esc() { printf '%s' "$1" | sed 's/[&/\]/\\&/g'; }

FILES=$(find . -type f \( -name '*.yml' -o -name '*.yaml' -o -name '*.md' -o -name '*.d2' -o -name '.goosehints' \) -not -path './.git/*' -not -name 'init.sh' -not -name 'LICENSE')

REPLACEMENTS=(
  "__PROJECT_NAME__|$(esc "$PROJECT_NAME")"
  "__PROJECT_DESCRIPTION__|$(esc "$PROJECT_DESC")"
  "__LANGUAGE__|$(esc "$LANGUAGE")"
  "__LANGUAGE_VERSION__|$(esc "$LANG_VERSION")"
  "__BUILD_CMD__|$(esc "$BUILD_CMD")"
  "__TEST_CMD__|$(esc "$TEST_CMD")"
  "__LINT_CMD__|$(esc "$LINT_CMD")"
  "__FORMAT_CMD__|$(esc "$FORMAT_CMD")"
  "__GOOSE_PROVIDER__|$(esc "${GOOSE_PROVIDER:-$PROVIDER}")"
  "__GOOSE_MODEL__|$(esc "$GOOSE_MODEL")"
  "__API_KEY_SECRET__|$(esc "$API_KEY_SECRET")"
  "__SETUP_ACTION__|$(esc "$SETUP_ACTION")"
  "__SETUP_WITH__|$(esc "$SETUP_WITH")"
)

count=0
for f in $FILES; do
  for pair in "${REPLACEMENTS[@]}"; do
    placeholder="${pair%%|*}"
    value="${pair#*|}"
    if grep -q "$placeholder" "$f" 2>/dev/null; then
      sedi "s|${placeholder}|${value}|g" "$f"
      count=$((count + 1))
    fi
  done
done

echo "    Replaced placeholders across ${count} file-placeholder pairs"

# ── Optional: re-render D2 diagram ───────────────────────────

if command -v d2 &>/dev/null; then
  echo "    Re-rendering pipeline diagram..."
  d2 --theme 200 --layout elk docs/pipeline-flow.d2 docs/pipeline-flow.svg 2>/dev/null && \
    echo "    Updated docs/pipeline-flow.svg" || \
    echo "    Warning: D2 render failed (diagram may need manual update)"
else
  echo "    Note: Install d2 (https://d2lang.com) to re-render the pipeline diagram"
fi

# ── Self-destruct ─────────────────────────────────────────────

rm -- "$0"
echo "    Removed init.sh"

# ══════════════════════════════════════════════════════════════
# Next steps
# ══════════════════════════════════════════════════════════════

echo ""
echo "  Done! Next steps:"
echo "  -----------------"
echo "  1. Add ${API_KEY_SECRET} to repo Settings > Secrets > Actions"
echo "  2. Enable GitHub Copilot coding agent (Settings > Copilot > Coding agent)"
echo "  3. git add -A && git commit -m 'Initialize AI pipeline' && git push"
echo "  4. Run the 'Sync Labels' workflow from the Actions tab"
echo ""
