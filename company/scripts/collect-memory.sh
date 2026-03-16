#!/usr/bin/env bash
# Collect memory for pipeline agents.
# Reads memory/MEMORY.md (semantic) + memory/episodic/*.md (episodic),
# applies filtering, and outputs context-budget-aware text to stdout.
#
# Usage:
#   bash collect-memory.sh                          # all memory, default 6KB budget
#   bash collect-memory.sh --budget 4096            # cap output at 4KB
#   bash collect-memory.sh --semantic-only          # MEMORY.md only
#   bash collect-memory.sh --tags "nat,relay"       # filter episodic by tags
#   bash collect-memory.sh --recent 5               # last 5 episodic entries
#   bash collect-memory.sh --budget 4096 --tags "nat" --recent 3
#
# Exit 0 always (graceful degradation). Warnings to stderr.
set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────
BUDGET=6144          # bytes
SEMANTIC_ONLY=false
TAGS=""
RECENT=5             # default: last 5 episodic entries
MEMORY_DIR="${MEMORY_DIR:-memory}"

# ── Parse args ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --budget)       BUDGET="$2"; shift 2 ;;
    --semantic-only) SEMANTIC_ONLY=true; shift ;;
    --tags)         TAGS="$2"; shift 2 ;;
    --recent)       RECENT="$2"; shift 2 ;;
    --memory-dir)   MEMORY_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; shift ;;
  esac
done

output=""

# ── Semantic layer ──────────────────────────────────────────────
semantic_file="${MEMORY_DIR}/MEMORY.md"
if [ -f "$semantic_file" ]; then
  semantic_content=$(cat "$semantic_file")
  output="${output}${semantic_content}"
else
  echo "::warning::No MEMORY.md found at ${semantic_file}" >&2
fi

if [ "$SEMANTIC_ONLY" = true ]; then
  # Truncate to budget and output
  echo "$output" | head -c "$BUDGET"
  exit 0
fi

# ── Episodic layer ──────────────────────────────────────────────
episodic_dir="${MEMORY_DIR}/episodic"
if [ ! -d "$episodic_dir" ]; then
  echo "::warning::No episodic directory at ${episodic_dir}" >&2
  echo "$output" | head -c "$BUDGET"
  exit 0
fi

# Collect episodic files sorted by filename (newest first, since filenames are date-prefixed)
# Compatible with bash 3+ (no mapfile)
all_files=()
while IFS= read -r f; do
  [ -n "$f" ] && all_files+=("$f")
done < <(ls -r "$episodic_dir"/*.md 2>/dev/null || true)

if [ ${#all_files[@]} -eq 0 ]; then
  echo "$output" | head -c "$BUDGET"
  exit 0
fi

# ── Tag filtering ───────────────────────────────────────────────
# Filter episodic entries by matching ANY of the requested tags
# against the YAML frontmatter `tags:` field.
filtered_files=()
if [ -n "$TAGS" ]; then
  IFS=',' read -ra tag_array <<< "$TAGS"
  for file in "${all_files[@]}"; do
    # Extract tags line from YAML frontmatter (between --- markers)
    file_tags=$(awk 'BEGIN{n=0} /^---$/{n++; next} n==1 && /^tags:/{print}' "$file" 2>/dev/null || echo "")
    matched=false
    for tag in "${tag_array[@]}"; do
      tag=$(echo "$tag" | xargs)  # trim whitespace
      if echo "$file_tags" | grep -qi "$tag"; then
        matched=true
        break
      fi
    done
    if [ "$matched" = true ]; then
      filtered_files+=("$file")
    fi
  done
else
  filtered_files=("${all_files[@]}")
fi

# ── Recency limit ──────────────────────────────────────────────
if [ ${#filtered_files[@]} -gt "$RECENT" ]; then
  filtered_files=("${filtered_files[@]:0:$RECENT}")
fi

# ── Build episodic output ──────────────────────────────────────
if [ ${#filtered_files[@]} -gt 0 ]; then
  output="${output}

---

# Recent Episodic Memory (${#filtered_files[@]} entries)
"
  for file in "${filtered_files[@]}"; do
    filename=$(basename "$file" .md)
    # Extract body: everything after the closing --- of YAML frontmatter
    body=$(awk 'BEGIN{n=0} /^---$/{n++; next} n>=2{print}' "$file" 2>/dev/null || echo "")
    # Extract summary: text between "## Summary" and next "##"
    summary=$(echo "$body" | awk '/^## Summary$/{found=1; next} /^##/{found=0} found{print}' | head -3 | tr '\n' ' ' | sed 's/  */ /g' | sed 's/^ *//;s/ *$//')

    if [ -n "$summary" ]; then
      output="${output}
## ${filename}
${summary}
"
    fi
  done
fi

# ── Budget enforcement ──────────────────────────────────────────
echo "$output" | head -c "$BUDGET"
