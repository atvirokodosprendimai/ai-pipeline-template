#!/usr/bin/env bash
# Collect infrastructure health signals for the company control loop.
# Reads endpoints from company/health.json.
# Output: JSON to stdout.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
HEALTH_FILE="$REPO_ROOT/company/health.json"

check_health() {
  local name="$1" url="$2"
  local status="unknown" latency_ms=0
  if [ -n "$url" ] && [ "$url" != "null" ]; then
    start=$(date +%s%N 2>/dev/null || echo 0)
    http_code=$(curl -sf -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 10 "$url" 2>/dev/null || echo "000")
    end=$(date +%s%N 2>/dev/null || echo 0)
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 400 ] 2>/dev/null; then
      status="up"
    elif [ "$http_code" = "000" ]; then
      status="unreachable"
    else
      status="error:$http_code"
    fi
    if [ "$start" != "0" ] && [ "$end" != "0" ]; then
      latency_ms=$(( (end - start) / 1000000 ))
    fi
  fi
  jq -n --arg name "$name" --arg url "$url" --arg status "$status" --argjson latency "$latency_ms" \
    '{name: $name, url: $url, status: $status, latency_ms: $latency}'
}

# Read endpoints from health.json
results="[]"
if [ -f "$HEALTH_FILE" ]; then
  endpoints=$(jq -c '.endpoints // [] | .[]' "$HEALTH_FILE" 2>/dev/null || echo "")
  while IFS= read -r ep; do
    [ -z "$ep" ] && continue
    name=$(echo "$ep" | jq -r '.name')
    url=$(echo "$ep" | jq -r '.url')
    result=$(check_health "$name" "$url")
    results=$(echo "$results" | jq --argjson r "$result" '. + [$r]')
  done <<< "$endpoints"
fi

jq -n \
  --arg collected_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --argjson services "$results" \
  '{
    source: "infrastructure",
    collected_at: $collected_at,
    services: $services
  }'
