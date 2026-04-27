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
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

resource "hcloud_ssh_key" "deploy" {
  name       = "mentisdb-deploy"
  public_key = var.deploy_ssh_public_key
}

resource "hcloud_firewall" "mentisdb" {
  name = "mentisdb-public"

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

resource "hcloud_server" "mentisdb" {
  name         = "mentisdb-prod"
  image        = "ubuntu-24.04"
  server_type  = "cx22"
  location     = "fra1"
  ssh_keys     = [hcloud_ssh_key.deploy.id]
  firewall_ids = [hcloud_firewall.mentisdb.id]
  user_data = templatefile("${path.module}/cloud-init.sh.tpl", {
    domain_name       = var.domain_name
    letsencrypt_email = var.letsencrypt_email
    mentisdb_version  = var.mentisdb_version
  })
  labels = {
    role = "mentisdb"
    env  = "prod"
  }
}

resource "cloudflare_record" "mem_beerpub" {
  zone_id = var.beerpub_cloudflare_zone_id
  name    = "mem"
  value   = hcloud_server.mentisdb.ipv4_address
  type    = "A"
  ttl     = 300
  proxied = false
}
