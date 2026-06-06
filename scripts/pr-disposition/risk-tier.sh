#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_PATH="${PR_DISPOSITION_CONFIG:-${ROOT_DIR}/.compound-engineering/config.local.yaml}"

patterns=(
  '^docs/(outreach|customers)/'
  '^company/system-prompt\.md$'
  '(^|/)(auth|authn|oauth|secrets?|payments?|billing|stripe|polar)(/|$)'
  '(^|/)[^/]*(auth|secret|token|credential|payment|billing|stripe|polar)[^/]*'
)

if [[ -f "$CONFIG_PATH" ]]; then
  while IFS= read -r pattern; do
    [[ -n "$pattern" ]] && patterns+=("$pattern")
  done < <(python3 - "$CONFIG_PATH" <<'PY'
import ast
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text().splitlines()
in_list = False
for raw in lines:
    line = raw.rstrip()
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    if re.match(r"^pr_disposition_high_risk_paths\s*:", stripped):
        value = stripped.split(":", 1)[1].strip()
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = ast.literal_eval(value)
                for item in parsed:
                    print(str(item))
            except Exception:
                pass
        in_list = True
        continue
    if in_list:
        if re.match(r"^[A-Za-z0-9_.-]+\s*:", stripped):
            break
        if stripped.startswith("-"):
            item = stripped[1:].strip()
            if " #" in item:
                item = item.split(" #", 1)[0].strip()
            if (item.startswith("'") and item.endswith("'")) or (item.startswith('"') and item.endswith('"')):
                item = item[1:-1]
            if item:
                print(item)
PY
  )
fi

input_files() {
  if [[ $# -gt 0 ]]; then
    if [[ -f "$1" ]]; then
      cat "$1"
    else
      printf '%s\n' "$1"
    fi
  else
    cat
  fi
}

while IFS= read -r changed_path; do
  [[ -n "$changed_path" ]] || continue
  for pattern in "${patterns[@]}"; do
    if [[ "$changed_path" =~ $pattern ]]; then
      echo "high"
      exit 0
    fi
  done
done < <(input_files "$@")

echo "low"
