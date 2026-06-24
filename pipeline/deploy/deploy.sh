#!/usr/bin/env bash
# Deploy / update the wgmesh-pipeline on a Hetzner (or any systemd) host.
# Idempotent: safe to re-run for updates (git pull + reinstall + restart).
#
# Usage (run as root on the host):
#   ./deploy.sh                     # update from the checked-out repo
#   REPO_URL=... ./deploy.sh        # first install: clone into /opt/wgmesh-pipeline
#
# Preconditions: Python 3.11+, git, and the Goose CLI installed on the host;
# /etc/wgmesh-pipeline/env populated from env.example (chmod 600).
set -euo pipefail

APP_DIR=/opt/wgmesh-pipeline
ENV_FILE=/etc/wgmesh-pipeline/env
SERVICE=wgmesh-pipeline

if [ ! -f "$ENV_FILE" ]; then
  echo "::error:: $ENV_FILE missing — copy pipeline/deploy/env.example, fill secrets, chmod 600" >&2
  exit 1
fi

# 1. Source: clone on first run, pull on updates.
if [ ! -d "$APP_DIR/.git" ]; then
  : "${REPO_URL:?set REPO_URL for first install}"
  git clone "$REPO_URL" "$APP_DIR"
fi
git -C "$APP_DIR" fetch --depth 1 origin main
git -C "$APP_DIR" reset --hard origin/main

# 2. venv + package.
if [ ! -d "$APP_DIR/.venv" ]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -e "$APP_DIR/pipeline"

# 3. Smoke test before swapping the running service — never deploy red.
( cd "$APP_DIR" && "$APP_DIR/.venv/bin/python" -m pytest pipeline/tests/ -q )

# 4. systemd unit + (re)start.
install -m 0644 "$APP_DIR/pipeline/deploy/wgmesh-pipeline.service" \
  /etc/systemd/system/${SERVICE}.service
id wgmesh >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin wgmesh
chown -R wgmesh:wgmesh "$APP_DIR"
# Writable, persistent cache for the bubblewrap-sandboxed run_bash tool
# (GOMODCACHE/GOCACHE/GOPATH/pip live here; the host root is read-only inside
# the sandbox). Created after useradd so wgmesh owns it.
install -d -m 0700 -o wgmesh -g wgmesh /var/cache/wgmesh-agent
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"
systemctl --no-pager status "$SERVICE" | head -n 15
