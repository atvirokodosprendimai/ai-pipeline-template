terraform {
  required_version = ">= 1.9.0"

  backend "s3" {
    bucket = "atvirokodosprendimai-tfstate"
    key    = "mentisdb/terraform.tfstate"
    region = "us-east-1"

    endpoints = {
      s3 = "https://fsn1.your-objectstorage.com"
    }

    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
    use_path_style              = true
  }

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

provider "hcloud" {}

provider "cloudflare" {
  # Configured via CLOUDFLARE_API_TOKEN env var
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
