#!/bin/bash
# MentisDB cloud-init bootstrap
# Generated from cloud-init.sh.tpl by terraform
# Runs as root on first boot.
set -euo pipefail
trap 'echo "MentisDB cloud-init bootstrap failed on line $LINENO (pid $$)" >&2' ERR

DOMAIN="${domain_name}"
EMAIL="${letsencrypt_email}"
VERSION="${mentisdb_version}"
# Single-quoted heredoc neutralizes shell metachars in the rendered password.
BASIC_AUTH_PASSWORD=$(cat <<'BASIC_AUTH_PASSWORD_END'
${basic_auth_password}
BASIC_AUTH_PASSWORD_END
)
# Validate: non-empty + no newlines/CRLF.
# (An empty TF var silently creates empty Basic Auth. A var with embedded
#  newlines would only deliver up to the first \n via stdin to htpasswd,
#  producing credentials that don't match the intended secret.)
if [ -z "$BASIC_AUTH_PASSWORD" ] || [ "$(printf '%s' "$BASIC_AUTH_PASSWORD" | tr -d '[:space:]')" = "" ]; then
  echo "ERROR: basic_auth_password is empty or whitespace-only" >&2
  exit 1
fi
case "$BASIC_AUTH_PASSWORD" in
  *$'\n'* | *$'\r'*)
    echo "ERROR: basic_auth_password contains newline/CRLF — rejecting (would truncate via htpasswd -i)" >&2
    exit 1
    ;;
esac
DATA_DIR="/var/lib/mentisdb"
USER="mentisdb"

# --- 1. Packages ---
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y \
  build-essential curl git nginx certbot python3-certbot-nginx ufw \
  pkg-config libssl-dev libasound2-dev ca-certificates apache2-utils

# --- 2. System user + dirs ---
id -u "$USER" >/dev/null 2>&1 || \
  useradd --system --shell /bin/bash --home "$DATA_DIR" --create-home "$USER"
install -d -o "$USER" -g "$USER" -m 0750 "$DATA_DIR"
install -d -m 0755 /etc/mentisdb

# --- 3. Rust toolchain (pinned rustup-init with checksum) ---
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)
    RUSTUP_URL=https://static.rust-lang.org/rustup/archive/1.27.1/x86_64-unknown-linux-gnu/rustup-init
    RUSTUP_SHA=6aeece6993e902708983b209d04c0d1dbb14ebb405ddb87def578d41f920f56d
    ;;
  aarch64)
    RUSTUP_URL=https://static.rust-lang.org/rustup/archive/1.27.1/aarch64-unknown-linux-gnu/rustup-init
    RUSTUP_SHA=1cffbf51e63e634c746f741de50649bbbcbd9dbe1de363c9ecef64e278dba2b2
    ;;
  *)
    echo "Unsupported architecture: $ARCH" >&2; exit 1;;
esac

curl -fsSL --output /tmp/rustup-init "$RUSTUP_URL"
echo "$RUSTUP_SHA  /tmp/rustup-init" | sha256sum -c -
chmod +x /tmp/rustup-init

sudo -u "$USER" -H \
  HOME="$DATA_DIR" CARGO_HOME="$DATA_DIR/.cargo" RUSTUP_HOME="$DATA_DIR/.rustup" \
  /tmp/rustup-init -y --default-toolchain stable --profile minimal --no-modify-path
rm -f /tmp/rustup-init

# --- 4. Install mentisdbd ---
sudo -u "$USER" -H \
  HOME="$DATA_DIR" CARGO_HOME="$DATA_DIR/.cargo" RUSTUP_HOME="$DATA_DIR/.rustup" \
  "$DATA_DIR/.cargo/bin/cargo" install mentisdb --version "$VERSION" --locked

ln -sf "$DATA_DIR/.cargo/bin/mentisdbd" /usr/local/bin/mentisdbd

# --- 5. mentisdbd env file ---
cat > /etc/mentisdb/mentisdbd.env <<EOF
MENTISDB_DIR=$DATA_DIR
MENTISDB_BIND_HOST=127.0.0.1
MENTISDB_MCP_PORT=9471
MENTISDB_REST_PORT=9472
MENTISDB_HTTPS_MCP_PORT=0
MENTISDB_HTTPS_REST_PORT=0
MENTISDB_DASHBOARD_PORT=9475
MENTISDB_STARTUP_SOUND=false
MENTISDB_THOUGHT_SOUNDS=false
RUST_LOG=info
EOF
chown "$USER:$USER" /etc/mentisdb/mentisdbd.env
chmod 0640 /etc/mentisdb/mentisdbd.env

# --- 6. systemd unit ---
cat > /etc/systemd/system/mentisdbd.service <<EOF
[Unit]
Description=MentisDB durable memory daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$USER
EnvironmentFile=/etc/mentisdb/mentisdbd.env
# mentisdbd unconditionally opens /dev/tty for TUI init even when not interactive.
# Wrap in `script` to allocate a fake PTY so the daemon can start under systemd.
# (mentisdb 0.9.5 — track upstream for headless flag)
ExecStart=/usr/bin/script -qfc /usr/local/bin/mentisdbd /dev/null
Restart=on-failure
RestartSec=5
StateDirectory=mentisdb
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now mentisdbd

# --- 7. nginx (HTTP-only initial; certbot rewrites for 443) ---
cat > /etc/nginx/sites-available/mentisdb <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        auth_basic           "MentisDB";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:9472;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }
}
EOF

# --- 7b. Basic Auth credentials file ---
# Use -i (stdin) instead of -b (argv) to avoid leaking the password via /proc.
# Pre-create the htpasswd file with restrictive perms, then run htpasswd
# without -c (no truncating create). This avoids the brief race window where
# `htpasswd -c` would create the file with umask-default perms (often 0644 =
# world-readable) before the explicit chmod ran.
install -o root -g www-data -m 0640 /dev/null /etc/nginx/.htpasswd
# Newline-terminated stdin — some htpasswd implementations expect a line.
printf '%s\n' "$BASIC_AUTH_PASSWORD" | htpasswd -iB /etc/nginx/.htpasswd mentisdb
# Drop the rendered password from the in-memory shell variable; the bcrypt
# hash in /etc/nginx/.htpasswd is the only artifact we want to retain.
unset BASIC_AUTH_PASSWORD
# cloud-init persists the rendered user-data at /var/lib/cloud/instance/user-data.txt
# with the plaintext password. Shred + remove so the only on-disk credential
# representation is the bcrypt hash in nginx's .htpasswd.
if [ -f /var/lib/cloud/instance/user-data.txt ]; then
  shred -u /var/lib/cloud/instance/user-data.txt 2>/dev/null || rm -f /var/lib/cloud/instance/user-data.txt
fi

ln -sf /etc/nginx/sites-available/mentisdb /etc/nginx/sites-enabled/mentisdb
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# --- 8. Let's Encrypt + auto-renewal ---
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$EMAIL" --redirect
( crontab -l 2>/dev/null || true; echo "17 3 * * * /usr/bin/certbot renew --quiet" ) | crontab -

# --- 9. ufw firewall ---
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "MentisDB cloud-init bootstrap complete."
