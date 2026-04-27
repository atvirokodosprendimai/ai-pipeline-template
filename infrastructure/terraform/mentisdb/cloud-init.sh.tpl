#!/bin/bash
# MentisDB cloud-init bootstrap (docker variant)
# Generated from cloud-init.sh.tpl by terraform
# Runs as root on first boot.
set -euo pipefail
trap 'echo "MentisDB cloud-init bootstrap failed on line $LINENO (pid $$)" >&2' ERR

DOMAIN="${domain_name}"
EMAIL="${letsencrypt_email}"
IMAGE="${mentisdb_image}"
# Single-quoted heredoc neutralizes shell metachars in the rendered password.
BASIC_AUTH_PASSWORD=$(cat <<'BASIC_AUTH_PASSWORD_END'
${basic_auth_password}
BASIC_AUTH_PASSWORD_END
)
# Validate: non-empty + no newlines/CRLF.
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

# --- 1. Packages ---
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y \
  curl nginx certbot python3-certbot-nginx ufw \
  ca-certificates apache2-utils docker.io

# --- 2. Data dir ---
# Container internally runs as uid 991; ensure host dir is writable by it.
install -d -o 991 -g 991 -m 0750 "$DATA_DIR"

# --- 3. Pull mentisdbd image + systemd unit wrapping `docker run` ---
systemctl enable --now docker
docker pull "$IMAGE"

cat > /etc/systemd/system/mentisdbd.service <<EOF
[Unit]
Description=MentisDB durable memory daemon (containerized)
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=simple
ExecStartPre=-/usr/bin/docker stop mentisdbd
ExecStartPre=-/usr/bin/docker rm mentisdbd
# -t allocates a pseudo-TTY satisfying mentisdbd's /dev/tty probe.
# Bind 0.0.0.0 inside container; published ports limited to 127.0.0.1 on host.
# nginx on the host proxies HTTPS:443 -> 127.0.0.1:9472.
ExecStart=/usr/bin/docker run --rm --name mentisdbd -t \\
  -p 127.0.0.1:9471:9471 \\
  -p 127.0.0.1:9472:9472 \\
  -p 127.0.0.1:9475:9475 \\
  -v $DATA_DIR:/var/lib/mentisdb \\
  -e MENTISDB_BIND_HOST=0.0.0.0 \\
  -e MENTISDB_STARTUP_SOUND=false \\
  -e MENTISDB_THOUGHT_SOUNDS=false \\
  -e RUST_LOG=info \\
  $IMAGE
ExecStop=/usr/bin/docker stop mentisdbd
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now mentisdbd

# --- 4. nginx (HTTP-only initial; certbot rewrites for 443) ---
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

# --- 4b. Basic Auth credentials file ---
install -o root -g www-data -m 0640 /dev/null /etc/nginx/.htpasswd
printf '%s\n' "$BASIC_AUTH_PASSWORD" | htpasswd -iB /etc/nginx/.htpasswd mentisdb
unset BASIC_AUTH_PASSWORD
if [ -f /var/lib/cloud/instance/user-data.txt ]; then
  shred -u /var/lib/cloud/instance/user-data.txt 2>/dev/null || rm -f /var/lib/cloud/instance/user-data.txt
fi

ln -sf /etc/nginx/sites-available/mentisdb /etc/nginx/sites-enabled/mentisdb
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# --- 5. Let's Encrypt + auto-renewal ---
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$EMAIL" --redirect
( crontab -l 2>/dev/null || true; echo "17 3 * * * /usr/bin/certbot renew --quiet" ) | crontab -

# --- 6. ufw firewall ---
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "MentisDB cloud-init bootstrap complete (image: $IMAGE)."
