variable "deploy_ssh_public_key" {
  description = "SSH public key (OpenSSH format) for Hetzner mentisdb-prod server"
  type        = string
}

variable "beerpub_cloudflare_zone_id" {
  description = "Cloudflare zone ID for beerpub.dev — used for mem.beerpub.dev A record"
  type        = string
}
