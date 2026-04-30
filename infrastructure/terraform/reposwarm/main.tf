terraform {
  required_version = ">= 1.8.0"

  backend "s3" {}

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.50"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

resource "tls_private_key" "deploy" {
  algorithm = "ED25519"
}

resource "hcloud_ssh_key" "deploy" {
  name       = "reposwarm-deploy"
  public_key = trimspace(tls_private_key.deploy.public_key_openssh)
}

resource "hcloud_firewall" "reposwarm" {
  name = "reposwarm-public"

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "reposwarm" {
  name         = "reposwarm-prod"
  image        = "ubuntu-24.04"
  server_type  = "cx23"
  location     = "hel1"
  ssh_keys     = [hcloud_ssh_key.deploy.id]
  firewall_ids = [hcloud_firewall.reposwarm.id]
  user_data = templatefile("${path.module}/cloud-init.sh.tpl", {
    domain_name          = var.domain_name
    letsencrypt_email    = var.letsencrypt_email
    reposwarm_api_token  = var.reposwarm_api_token
    anthropic_api_key    = var.anthropic_api_key
    openrouter_api_key   = var.openrouter_api_key
    github_token         = var.github_token
    llm_provider         = var.llm_provider
  })
  labels = {
    role = "reposwarm"
    env  = "prod"
  }
}

resource "cloudflare_record" "swarm_beerpub" {
  zone_id = var.beerpub_cloudflare_zone_id
  name    = "swarm"
  value   = hcloud_server.reposwarm.ipv4_address
  type    = "A"
  ttl     = 300
  proxied = false
}
