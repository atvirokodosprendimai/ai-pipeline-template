# MentisDB Ansible Deployment

This playbook installs the MentisDB Rust daemon (`mentisdbd`) on a Hetzner VPS, runs it under systemd as a dedicated `mentisdb` user, and exposes only the REST API through nginx and Let's Encrypt.

## Prerequisites

- Ansible installed on the operator's machine.
- SSH access to the Hetzner VPS.
- A DNS A record for `mem.beerpub.dev` pointing at the server IP.
- Ubuntu 24.04 on the target server.

## Inventory

Create `inventory.ini`:

```ini
[mentisdb]
mem.beerpub.dev ansible_user=root
```

Using the server IP is also valid:

```ini
[mentisdb]
203.0.113.10 ansible_user=root
```

## Run

From the repository root:

```bash
ansible-playbook -i inventory.ini infrastructure/ansible/mentisdb-deploy.yml
```

Override variables when needed:

```bash
ansible-playbook -i inventory.ini infrastructure/ansible/mentisdb-deploy.yml \
  -e domain_name=mem.beerpub.dev \
  -e mentisdb_version=0.9.5.41
```

## Architecture

```text
Internet → 443 (nginx + Let's Encrypt) → 127.0.0.1:9472 (mentisdbd REST)
```

`mentisdbd` binds to `127.0.0.1`; HTTPS listeners are disabled in the daemon. Public access is limited to the REST API through nginx.

MCP on `9471` and the dashboard on `9475` stay private. Access them through an SSH tunnel:

```bash
ssh -L 9471:127.0.0.1:9471 -L 9475:127.0.0.1:9475 root@mem.beerpub.dev
```

## Update Process

Set `mentisdb_version` to the desired crates.io version and re-run the playbook:

```bash
ansible-playbook -i inventory.ini infrastructure/ansible/mentisdb-deploy.yml \
  -e mentisdb_version=0.9.5.41
```
