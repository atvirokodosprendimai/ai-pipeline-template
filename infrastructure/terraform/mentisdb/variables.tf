variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token (Zone DNS Edit on beerpub.dev)"
  type        = string
  sensitive   = true
}

variable "beerpub_cloudflare_zone_id" {
  description = "Cloudflare zone ID for beerpub.dev — used for mem.beerpub.dev A record"
  type        = string
}

variable "domain_name" {
  description = "Public domain for MentisDB (Let's Encrypt cert + nginx server_name)"
  type        = string
  default     = "mem.beerpub.dev"
}

variable "letsencrypt_email" {
  description = "Email for Let's Encrypt registration"
  type        = string
  default     = "admin@beerpub.dev"
}

variable "mentisdb_version" {
  description = "MentisDB crates.io version to install"
  type        = string
  default     = "0.9.5"
}

variable "mentisdb_password" {
  description = "HTTP Basic Auth password for the mentisdb user (sourced from MENTISDB_PASSWORD org secret via TF_VAR_mentisdb_password). Single source of truth: the org secret. Rotate by updating the secret + re-applying."
  type        = string
  sensitive   = true
}
