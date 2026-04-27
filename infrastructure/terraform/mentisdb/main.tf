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
  name       = "mentisdb-deploy"
  public_key = trimspace(tls_private_key.deploy.public_key_openssh)
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

resource "hcloud_volume" "mentisdb_data" {
  name              = "mentisdb-data"
  size              = var.mentisdb_volume_size_gb
  location          = "hel1"
  format            = "ext4"
  delete_protection = true

  lifecycle {
    # Defense in depth — even if delete_protection is dropped, terraform
    # itself will refuse to destroy this resource without explicit
    # `terraform state rm` first. Protects accumulated mentisdb chain
    # data from being wiped on routine `tofu apply -replace` flows.
    prevent_destroy = true
  }
}

resource "hcloud_server" "mentisdb" {
  name         = "mentisdb-prod"
  image        = "ubuntu-24.04"
  server_type  = "cx23"
  location     = "hel1"
  ssh_keys     = [hcloud_ssh_key.deploy.id]
  firewall_ids = [hcloud_firewall.mentisdb.id]
  # Attach the volume at server creation so it's available before
  # cloud-init runs the docker mount logic.
  user_data = templatefile("${path.module}/cloud-init.sh.tpl", {
    domain_name         = var.domain_name
    letsencrypt_email   = var.letsencrypt_email
    mentisdb_image      = var.mentisdb_image
    basic_auth_password = var.mentisdb_password
    volume_id           = hcloud_volume.mentisdb_data.id
  })
  labels = {
    role = "mentisdb"
    env  = "prod"
  }
}

resource "hcloud_volume_attachment" "mentisdb_data" {
  volume_id = hcloud_volume.mentisdb_data.id
  server_id = hcloud_server.mentisdb.id
  automount = false
}

resource "cloudflare_record" "mem_beerpub" {
  zone_id = var.beerpub_cloudflare_zone_id
  name    = "mem"
  value   = hcloud_server.mentisdb.ipv4_address
  type    = "A"
  ttl     = 300
  proxied = false
}
