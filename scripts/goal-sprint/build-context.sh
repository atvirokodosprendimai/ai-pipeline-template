#!/usr/bin/env bash
# non-fatal by design — missing optional inputs must not abort context assembly (see repo bash-helper contract).
set -uo pipefail
trap 'status=$?; echo "WARN: build-context command failed near line $LINENO (status $status)" >&2; true' ERR

out="/tmp/goal_sprint_user.txt"

{
  echo "# Goal Sprint Context"
  echo ""
  echo "Generated at: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo ""

  echo "## STRATEGY.md"
  if [ -f STRATEGY.md ]; then
    cat STRATEGY.md || true
  else
    echo "STRATEGY.md not found."
  fi
  echo ""

  echo "## Latest Pulse Report"
  latest_pulse="$(ls -1 docs/pulse-reports/*.md 2>/dev/null | sort | tail -1 || true)"
  if [ -n "${latest_pulse:-}" ] && [ -f "$latest_pulse" ]; then
    echo "Source: $latest_pulse"
    cat "$latest_pulse" || true
  else
    echo "No pulse report found."
  fi
  echo ""

  echo "## Loop State"
  if [ -f company/loop-state.json ]; then
    if command -v jq >/dev/null 2>&1; then
      jq . company/loop-state.json || cat company/loop-state.json || true
    else
      cat company/loop-state.json || true
    fi
  else
    echo "company/loop-state.json not found."
  fi
  echo ""

  echo "## Prior Goal Sprint Fingerprint"
  if [ -f company/goal-sprint-state.json ]; then
    if command -v jq >/dev/null 2>&1; then
      prior="$(jq -r '.last_fingerprint // ""' company/goal-sprint-state.json 2>/dev/null || true)"
      echo "${prior:-none}"
    else
      cat company/goal-sprint-state.json || true
    fi
  else
    echo "none"
  fi
} > "$out"

if [ ! -s "$out" ]; then
  echo "Goal sprint context unavailable; proceed from STRATEGY.md when present." > "$out"
fi

echo "Wrote $out ($(wc -c < "$out" | tr -d ' ') bytes)"
