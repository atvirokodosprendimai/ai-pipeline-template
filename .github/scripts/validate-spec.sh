#!/usr/bin/env bash
set -euo pipefail

# Spec Validation — structural checks for AI-generated spec files.
# Output: one line per check — CHECK_NAME|PASS| or CHECK_NAME|FAIL|detail or CHECK_NAME|WARN|detail
# Exit: 0 if zero FAILs, 1 if any FAIL.

SPEC_FILE="${1:?Usage: validate-spec.sh <spec-file>}"

if [ ! -f "$SPEC_FILE" ]; then
  echo "SPEC_EXISTS|FAIL|File not found: $SPEC_FILE"
  exit 1
fi

CONTENT=$(cat "$SPEC_FILE")
ERRORS=0

# ── Helper: strip HTML comments and fenced code blocks ──
strip_comments_and_code() {
  sed '/<!--/,/-->/d' | sed '/^```/,/^```/d'
}

CLEAN=$(echo "$CONTENT" | strip_comments_and_code)

# ── Check 1: Required sections ──
REQUIRED_SECTIONS=(
  "## Classification"
  "## Deliverables"
  "## Problem Analysis"
  "## Implementation Tasks"
  "## Affected Files"
  "## Test Strategy"
  "## Estimated Complexity"
)

MISSING=""
for section in "${REQUIRED_SECTIONS[@]}"; do
  if ! echo "$CONTENT" | grep -qF "$section"; then
    MISSING="${MISSING}${section}, "
  fi
done

if [ -n "$MISSING" ]; then
  echo "REQUIRED_SECTIONS|FAIL|Missing: ${MISSING%, }"
  ERRORS=$((ERRORS + 1))
else
  echo "REQUIRED_SECTIONS|PASS|"
fi

# ── Check 2: No line number references ──
# Search cleaned content (no comments/code blocks) for line number patterns.
LINE_REFS=$(echo "$CLEAN" | grep -inE '(after line|at line|on line|lines? [0-9])' || true)

if [ -n "$LINE_REFS" ]; then
  # Grab first offending line for the detail message
  FIRST=$(echo "$LINE_REFS" | head -1 | sed 's/^[0-9]*://')
  echo "NO_LINE_NUMBERS|FAIL|Found line number reference: ${FIRST:0:120}"
  ERRORS=$((ERRORS + 1))
else
  echo "NO_LINE_NUMBERS|PASS|"
fi

# ── Check 3: Test file naming matches source ──
# Extract Affected Files section, check that source files have matching test files.
AF_SECTION=$(echo "$CONTENT" | sed -n '/^## Affected Files/,/^## /p' | sed '1d;$d')

if [ -n "$AF_SECTION" ]; then
  WARN_FILES=""
  while IFS= read -r line; do
    alt_test=""
    # Skip empty lines, comments, and lines with (no-test)
    [[ -z "$line" || "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" =~ "<!--" ]] && continue
    [[ "$line" =~ "(no-test)" ]] && continue

    # Extract file path (first non-whitespace token)
    filepath=$(echo "$line" | awk '{print $1}')

    # Skip if it's already a test file
    [[ "$filepath" =~ _test\. || "$filepath" =~ \.test\. || "$filepath" =~ __test__ || "$filepath" =~ /tests?/ ]] && continue
    # Skip non-code files
    [[ "$filepath" =~ \.(md|yml|yaml|json|toml|txt)$ ]] && continue

    # Derive expected test file name
    ext="${filepath##*.}"
    base="${filepath%.*}"
    case "$ext" in
      go)    expected_test="${base}_test.go" ;;
      py)    expected_test="${base}_test.py"
             alt_test="test_$(basename "$base").py" ;;
      ts|js) expected_test="${base}.test.${ext}" ;;
      *)     continue ;;  # skip unknown extensions
    esac

    # Check if test file exists in Affected Files
    if ! echo "$AF_SECTION" | grep -qF "$(basename "$expected_test")"; then
      # Check alt pattern for Python
      if [ -n "${alt_test:-}" ] && echo "$AF_SECTION" | grep -qF "$(basename "$alt_test")"; then
        continue
      fi
      WARN_FILES="${WARN_FILES}${filepath}, "
    fi
  done <<< "$AF_SECTION"

  if [ -n "$WARN_FILES" ]; then
    echo "TEST_FILE_MATCH|WARN|Source files without matching test: ${WARN_FILES%, }. Add test file or mark (no-test)."
  else
    echo "TEST_FILE_MATCH|PASS|"
  fi
else
  echo "TEST_FILE_MATCH|PASS|"
fi

# ── Check 4: No placeholder tokens ──
PLACEHOLDERS=$(echo "$CLEAN" | grep -oE '__[A-Z_]{3,}__' | sort -u || true)

if [ -n "$PLACEHOLDERS" ]; then
  echo "NO_PLACEHOLDERS|FAIL|Found placeholder tokens: $(echo "$PLACEHOLDERS" | tr '\n' ' ')"
  ERRORS=$((ERRORS + 1))
else
  echo "NO_PLACEHOLDERS|PASS|"
fi

# ── Check 5: Affected Files non-empty ──
AF_FILES=$(echo "$AF_SECTION" | grep -cE '\S' || true)

if [ "$AF_FILES" -lt 1 ]; then
  echo "AFFECTED_FILES|FAIL|Affected Files section is empty"
  ERRORS=$((ERRORS + 1))
else
  echo "AFFECTED_FILES|PASS|"
fi

# ── Check 6: Valid classification ──
# First non-empty, non-comment line after ## Classification heading.
CLASSIFICATION=$(echo "$CONTENT" | sed -n '/^## Classification/,/^## /p' | sed '1d;$d' | sed '/^<!--/,/-->/d' | grep -m1 '\S' || true)
CLASSIFICATION=$(echo "$CLASSIFICATION" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')

VALID_CLASSIFICATIONS="fix feature refactor wont-do needs-info"
if echo "$VALID_CLASSIFICATIONS" | grep -qw "$CLASSIFICATION"; then
  echo "VALID_CLASSIFICATION|PASS|"
else
  echo "VALID_CLASSIFICATION|FAIL|Classification '${CLASSIFICATION}' is not one of: $VALID_CLASSIFICATIONS"
  ERRORS=$((ERRORS + 1))
fi

# ── Exit ──
if [ "$ERRORS" -gt 0 ]; then
  exit 1
fi
exit 0
