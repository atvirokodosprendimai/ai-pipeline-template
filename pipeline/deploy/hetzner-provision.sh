#!/usr/bin/env bash
# Provision a Hetzner Cloud VM for the wgmesh-pipeline.
# Requires the `hcloud` CLI authenticated (HCLOUD_TOKEN) and an SSH key already
# uploaded to the project. Run from a workstation, NOT on the box.
#
#   HCLOUD_TOKEN=... SSH_KEY=my-key ./hetzner-provision.sh
#
# This only stands up the host + installs prerequisites. Secrets and the
# service come from deploy.sh, run on the box afterwards (see PHASE4-DEPLOY.md).
# Alternative (cheaper): co-locate on the existing chimney box and skip this —
# just run deploy.sh there.
set -euo pipefail

: "${HCLOUD_TOKEN:?set HCLOUD_TOKEN}"
: "${SSH_KEY:?set SSH_KEY (name of an uploaded hcloud SSH key)}"
NAME=${NAME:-wgmesh-pipeline}
TYPE=${TYPE:-cx22}          # 2 vCPU / 4 GB — ample for a single poll loop
IMAGE=${IMAGE:-ubuntu-24.04}
LOCATION=${LOCATION:-hel1}  # Helsinki

cloud_init=$(cat <<'CLOUD'
#cloud-config
package_update: true
# bubblewrap: OS sandbox for the agent's run_bash tool. iptables-persistent:
# persist the cloud-metadata egress block across reboot.
packages: [git, python3, python3-venv, python3-pip, curl, jq, bubblewrap, iptables-persistent]
runcmd:
  # Goose CLI (self-hosted, same install the Actions workflows used).
  - curl -fsSL https://github.com/block/goose/releases/latest/download/download_cli.sh | bash
  - install -d -m 700 /etc/wgmesh-pipeline
  # Block egress to cloud metadata (169.254.169.254 / fd00:ec2::254) — SSRF /
  # prompt-injection exfil hardening. Persisted via iptables-persistent.
  - iptables -I OUTPUT -d 169.254.169.254 -j REJECT
  - ip6tables -I OUTPUT -d fd00:ec2::254 -j REJECT
  - netfilter-persistent save
  # Operator then: scp env (chmod 600) + run pipeline/deploy/deploy.sh as root.
CLOUD
)

hcloud server create \
  --name "$NAME" \
  --type "$TYPE" \
  --image "$IMAGE" \
  --location "$LOCATION" \
  --ssh-key "$SSH_KEY" \
  --user-data-from-file <(printf '%s' "$cloud_init")

echo "Provisioned $NAME. Next:"
echo "  1. scp pipeline/deploy/env.example root@<ip>:/etc/wgmesh-pipeline/env  (fill secrets, chmod 600)"
echo "  2. ssh root@<ip>, REPO_URL=<this repo> bash /opt/.../deploy.sh"
