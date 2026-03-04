#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════
# AI Pipeline Template - Interactive Setup
# Replaces __PLACEHOLDER__ markers with your project's values,
# then removes itself.
#
# Compatible with bash 3.2+ (macOS default) and bash 4+.
# ══════════════════════════════════════════════════════════════

echo ""
echo "  AI Pipeline Template Setup"
echo "  =========================="
echo ""

# ── Language presets via functions (bash 3.2 compatible) ──────

get_preset() {
  local lang="$1" field="$2"
  case "${lang}:${field}" in
    go:version)        echo "1.23" ;;
    go:build)          echo "go build ./..." ;;
    go:test)           echo "go test ./..." ;;
    go:lint)           echo "go vet ./..." ;;
    go:fmt)            echo "gofmt -w ." ;;
    go:action)         echo "actions/setup-go@v5" ;;
    go:with)           echo "go-version" ;;
    node:version)      echo "20" ;;
    node:build)        echo "npm run build" ;;
    node:test)         echo "npm test" ;;
    node:lint)         echo "npm run lint" ;;
    node:fmt)          echo "prettier --write ." ;;
    node:action)       echo "actions/setup-node@v4" ;;
    node:with)         echo "node-version" ;;
    python:version)    echo "3.12" ;;
    python:build)      echo "python -m build" ;;
    python:test)       echo "pytest" ;;
    python:lint)       echo "ruff check ." ;;
    python:fmt)        echo "ruff format ." ;;
    python:action)     echo "actions/setup-python@v5" ;;
    python:with)       echo "python-version" ;;
    rust:version)      echo "stable" ;;
    rust:build)        echo "cargo build" ;;
    rust:test)         echo "cargo test" ;;
    rust:lint)         echo "cargo clippy" ;;
    rust:fmt)          echo "cargo fmt" ;;
    rust:action)       echo "dtolnay/rust-toolchain@stable" ;;
    rust:with)         echo "toolchain" ;;
    *)                 echo "" ;;
  esac
}

get_provider_preset() {
  local provider="$1" field="$2"
  case "${provider}:${field}" in
    google:model)      echo "gemini-2.0-flash" ;;
    google:key)        echo "GOOGLE_API_KEY" ;;
    openai:model)      echo "gpt-4o" ;;
    openai:key)        echo "OPENAI_API_KEY" ;;
    anthropic:model)   echo "claude-sonnet-4-20250514" ;;
    anthropic:key)     echo "ANTHROPIC_API_KEY" ;;
    *)                 echo "" ;;
  esac
}

get_observer_preset() {
  local provider="$1" field="$2"
  case "${provider}:${field}" in
    openrouter:model)  echo "anthropic/claude-sonnet-4" ;;
    openrouter:key)    echo "OPENROUTER_API_KEY" ;;
    openrouter:url)    echo "https://openrouter.ai/api/v1/chat/completions" ;;
    openai:model)      echo "gpt-4o" ;;
    openai:key)        echo "OPENAI_API_KEY" ;;
    openai:url)        echo "https://api.openai.com/v1/chat/completions" ;;
    anthropic:model)   echo "claude-sonnet-4-20250514" ;;
    anthropic:key)     echo "ANTHROPIC_API_KEY" ;;
    anthropic:url)     echo "https://api.anthropic.com/v1/messages" ;;
    *)                 echo "" ;;
  esac
}

# ── Helper: prompt with default ──────────────────────────────

prompt() {
  local var_name="$1"
  local prompt_text="$2"
  local default_val="${3:-}"

  if [ -n "$default_val" ]; then
    read -rp "  $prompt_text [$default_val]: " input
    eval "$var_name=\"${input:-$default_val}\""
  else
    local input=""
    while [ -z "$input" ]; do
      read -rp "  $prompt_text: " input
      if [ -z "$input" ]; then
        echo "    (required)"
      fi
    done
    eval "$var_name=\"$input\""
  fi
}

# ── Cross-platform sed ───────────────────────────────────────

if [ "$(uname)" = "Darwin" ]; then
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
while [ -z "$LANG_CHOICE" ]; do
  read -rp "  Language [go/node/python/rust/other]: " LANG_CHOICE
  case "$LANG_CHOICE" in
    go|node|python|rust|other) ;;
    *)
      echo "    Choose: go, node, python, rust, or other"
      LANG_CHOICE=""
      ;;
  esac
done

if [ "$LANG_CHOICE" != "other" ]; then
  echo "    Loaded ${LANG_CHOICE} presets"
  LANGUAGE="$LANG_CHOICE"
  DEFAULT_VERSION="$(get_preset "$LANG_CHOICE" version)"
  DEFAULT_BUILD="$(get_preset "$LANG_CHOICE" build)"
  DEFAULT_TEST="$(get_preset "$LANG_CHOICE" test)"
  DEFAULT_LINT="$(get_preset "$LANG_CHOICE" lint)"
  DEFAULT_FMT="$(get_preset "$LANG_CHOICE" fmt)"
  DEFAULT_ACTION="$(get_preset "$LANG_CHOICE" action)"
  DEFAULT_WITH="$(get_preset "$LANG_CHOICE" with)"
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
while [ -z "$PROVIDER" ]; do
  read -rp "  Provider [google/openai/anthropic/other]: " PROVIDER
  case "$PROVIDER" in
    google|openai|anthropic|other) ;;
    *)
      echo "    Choose: google, openai, anthropic, or other"
      PROVIDER=""
      ;;
  esac
done

if [ "$PROVIDER" != "other" ]; then
  DEFAULT_MODEL="$(get_provider_preset "$PROVIDER" model)"
  DEFAULT_KEY="$(get_provider_preset "$PROVIDER" key)"
  GOOSE_PROVIDER="$PROVIDER"
else
  prompt GOOSE_PROVIDER "Provider name"
  DEFAULT_MODEL=""
  DEFAULT_KEY=""
fi

prompt GOOSE_MODEL    "Model name"           "$DEFAULT_MODEL"
prompt API_KEY_SECRET "API key secret name"  "$DEFAULT_KEY"
echo ""

echo "  Observation Loop"
echo "  ----------------"
echo "  The observation loop runs daily, collects project state,"
echo "  sends it to an LLM for assessment, and creates issues."
echo ""

ENABLE_LOOP=""
while [ -z "$ENABLE_LOOP" ]; do
  read -rp "  Enable observation loop? [y/n] (y): " ENABLE_LOOP
  ENABLE_LOOP="${ENABLE_LOOP:-y}"
  case "$ENABLE_LOOP" in
    y|n) ;;
    *)
      echo "    Choose: y or n"
      ENABLE_LOOP=""
      ;;
  esac
done

if [ "$ENABLE_LOOP" = "y" ]; then
  echo ""
  OBSERVER_PROVIDER=""
  while [ -z "$OBSERVER_PROVIDER" ]; do
    read -rp "  Observer LLM provider [openrouter/openai/anthropic/other]: " OBSERVER_PROVIDER
    case "$OBSERVER_PROVIDER" in
      openrouter|openai|anthropic|other) ;;
      *)
        echo "    Choose: openrouter, openai, anthropic, or other"
        OBSERVER_PROVIDER=""
        ;;
    esac
  done

  if [ "$OBSERVER_PROVIDER" != "other" ]; then
    OBS_DEFAULT_MODEL="$(get_observer_preset "$OBSERVER_PROVIDER" model)"
    OBS_DEFAULT_KEY="$(get_observer_preset "$OBSERVER_PROVIDER" key)"
    OBS_DEFAULT_URL="$(get_observer_preset "$OBSERVER_PROVIDER" url)"
  else
    OBS_DEFAULT_MODEL=""
    OBS_DEFAULT_KEY=""
    OBS_DEFAULT_URL=""
  fi

  prompt OBSERVER_MODEL      "Observer model name"        "$OBS_DEFAULT_MODEL"
  prompt OBSERVER_KEY_SECRET "Observer API key secret"    "$OBS_DEFAULT_KEY"
  prompt OBSERVER_API_URL    "Observer API URL"           "$OBS_DEFAULT_URL"
  echo ""

  prompt HEALTH_ENDPOINTS "Health check URLs (comma-separated, or 'none')" "none"
  prompt AVAILABLE_CAPITAL "Available capital (EUR/year, or 'null')" "null"
  echo ""
fi

# ══════════════════════════════════════════════════════════════
# Replace placeholders
# ══════════════════════════════════════════════════════════════

echo "  Applying configuration..."

# Escape special characters for sed (forward slashes, ampersands, backslashes)
esc() { printf '%s' "$1" | sed 's/[&/\]/\\&/g'; }

FILES=$(find . -type f \( -name '*.yml' -o -name '*.yaml' -o -name '*.md' -o -name '*.json' -o -name '*.d2' -o -name '.goosehints' \) -not -path './.git/*' -not -name 'init.sh' -not -name 'LICENSE')

# Build replacement pairs (placeholder|value)
PAIRS=""
PAIRS="${PAIRS}__PROJECT_NAME__|$(esc "$PROJECT_NAME")
"
PAIRS="${PAIRS}__PROJECT_DESCRIPTION__|$(esc "$PROJECT_DESC")
"
PAIRS="${PAIRS}__LANGUAGE__|$(esc "$LANGUAGE")
"
PAIRS="${PAIRS}__LANGUAGE_VERSION__|$(esc "$LANG_VERSION")
"
PAIRS="${PAIRS}__BUILD_CMD__|$(esc "$BUILD_CMD")
"
PAIRS="${PAIRS}__TEST_CMD__|$(esc "$TEST_CMD")
"
PAIRS="${PAIRS}__LINT_CMD__|$(esc "$LINT_CMD")
"
PAIRS="${PAIRS}__FORMAT_CMD__|$(esc "$FORMAT_CMD")
"
PAIRS="${PAIRS}__GOOSE_PROVIDER__|$(esc "${GOOSE_PROVIDER:-$PROVIDER}")
"
PAIRS="${PAIRS}__GOOSE_MODEL__|$(esc "$GOOSE_MODEL")
"
PAIRS="${PAIRS}__API_KEY_SECRET__|$(esc "$API_KEY_SECRET")
"
PAIRS="${PAIRS}__SETUP_ACTION__|$(esc "$SETUP_ACTION")
"
PAIRS="${PAIRS}__SETUP_WITH__|$(esc "$SETUP_WITH")
"

if [ "${ENABLE_LOOP:-n}" = "y" ]; then
  PAIRS="${PAIRS}__OBSERVER_MODEL__|$(esc "$OBSERVER_MODEL")
"
  PAIRS="${PAIRS}__OBSERVER_API_KEY_SECRET__|$(esc "$OBSERVER_KEY_SECRET")
"
  PAIRS="${PAIRS}__OBSERVER_API_URL__|$(esc "$OBSERVER_API_URL")
"
fi

count=0
for f in $FILES; do
  echo "$PAIRS" | while IFS='|' read -r placeholder value; do
    [ -z "$placeholder" ] && continue
    if grep -q "$placeholder" "$f" 2>/dev/null; then
      sedi "s|${placeholder}|${value}|g" "$f"
    fi
  done
  count=$((count + 1))
done

echo "    Processed ${count} files"

# ── Observation loop setup ────────────────────────────────────

if [ "${ENABLE_LOOP:-n}" = "y" ]; then
  # Seed health.json with endpoints
  if [ "$HEALTH_ENDPOINTS" != "none" ] && [ -n "$HEALTH_ENDPOINTS" ]; then
    endpoints_json="[]"
    IFS=',' read -ra URLS <<< "$HEALTH_ENDPOINTS"
    for url in "${URLS[@]}"; do
      url=$(echo "$url" | xargs)  # trim whitespace
      name=$(echo "$url" | sed 's|https\?://||' | sed 's|/.*||' | sed 's|\.[^.]*$||')
      endpoints_json=$(echo "$endpoints_json" | jq --arg n "$name" --arg u "$url" '. + [{name: $n, url: $u}]')
    done
    echo "$endpoints_json" | jq '{endpoints: .}' > company/health.json
    echo "    Configured $(echo "$endpoints_json" | jq length) health endpoints"
  fi

  # Seed costs.json with available capital
  if [ "$AVAILABLE_CAPITAL" != "null" ] && [ -n "$AVAILABLE_CAPITAL" ]; then
    jq --argjson cap "$AVAILABLE_CAPITAL" '.runway.available_capital = $cap' company/costs.json > /tmp/costs.json
    mv /tmp/costs.json company/costs.json
    echo "    Set available capital: ${AVAILABLE_CAPITAL} EUR/year"
  fi

  echo "    Observation loop enabled"
else
  # Remove observation loop files
  rm -rf company/
  rm -f .github/workflows/observation-loop.yml
  echo "    Observation loop disabled — removed company/ and workflow"
fi

# ── Optional: re-render D2 diagram ───────────────────────────

if command -v d2 >/dev/null 2>&1; then
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
if [ "${ENABLE_LOOP:-n}" = "y" ]; then
  echo "  2. Add ${OBSERVER_KEY_SECRET} to repo Settings > Secrets > Actions"
  echo "  3. Add PUSH_TOKEN (PAT with contents:write) to repo Settings > Secrets > Actions"
  echo "  4. Enable GitHub Copilot coding agent (Settings > Copilot > Coding agent)"
  echo "  5. git add -A && git commit -m 'Initialize AI pipeline' && git push"
  echo "  6. Run the 'Sync Labels' workflow from the Actions tab"
else
  echo "  2. Enable GitHub Copilot coding agent (Settings > Copilot > Coding agent)"
  echo "  3. git add -A && git commit -m 'Initialize AI pipeline' && git push"
  echo "  4. Run the 'Sync Labels' workflow from the Actions tab"
fi
echo ""
