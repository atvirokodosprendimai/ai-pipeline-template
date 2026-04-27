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

# --- 2. Persistent volume mount ---
# Hetzner Volume ${volume_id} attached at server creation. Mount it at
# $DATA_DIR before any data is written so mentisdb chain data survives
# server replacement (tofu apply -replace=hcloud_server.mentisdb).
VOLUME_DEVICE="/dev/disk/by-id/scsi-0HC_Volume_${volume_id}"
echo "Waiting for volume device $VOLUME_DEVICE to appear..."
for _ in $(seq 1 60); do
  [ -e "$VOLUME_DEVICE" ] && break
  sleep 1
done
if [ ! -e "$VOLUME_DEVICE" ]; then
  echo "ERROR: volume device $VOLUME_DEVICE never appeared after 60s" >&2
  exit 1
fi
mkdir -p "$DATA_DIR"
# Mount idempotently: skip if already mounted (cloud-init re-runs are rare
# but keep the script safe to re-execute manually for diagnostics).
if ! mountpoint -q "$DATA_DIR"; then
  mount "$VOLUME_DEVICE" "$DATA_DIR"
fi
# Persist mount via /etc/fstab (nofail so a missing volume doesn't
# block boot; we'd rather have a degraded server we can SSH into than
# an emergency-shell boot we can't reach).
if ! grep -q "$VOLUME_DEVICE" /etc/fstab; then
  echo "$VOLUME_DEVICE  $DATA_DIR  ext4  discard,nofail,defaults  0  0" >> /etc/fstab
fi
# Container internally runs as uid 991; ensure host dir is writable by it.
chown -R 991:991 "$DATA_DIR"
chmod 0750 "$DATA_DIR"

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
