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

variable "mentisdb_image" {
  description = "Container image (with tag) for mentisdbd. Defaults to a fork tag while CloudLLM-ai/mentisdb#16 is pending merge; switch to ghcr.io/cloudllm-ai/mentisdb:0.9.5 once that PR lands."
  type        = string
  default     = "ghcr.io/nycterent/mentisdb:0.9.5-test4"
}

variable "mentisdb_volume_size_gb" {
  description = "Size (GB) of the Hetzner Volume that holds /var/lib/mentisdb. Volume survives server delete/recreate. Min 10."
  type        = number
  default     = 10

  validation {
    condition     = var.mentisdb_volume_size_gb >= 10
    error_message = "Hetzner Volumes have a 10GB minimum."
  }
}

variable "mentisdb_password" {
  description = "HTTP Basic Auth password for the mentisdb user (sourced from MENTISDB_PASSWORD org secret via TF_VAR_mentisdb_password). Single source of truth: the org secret. Rotate by updating the secret + re-applying."
  type        = string
  sensitive   = true
}
