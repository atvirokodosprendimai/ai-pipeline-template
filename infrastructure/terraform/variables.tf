# Terraform Variables for AI Pipeline Infrastructure

variable "github_push_token" {
  description = "GitHub Personal Access Token with repo scope"
  type        = string
  sensitive   = true
}

variable "openrouter_api_key" {
  description = "OpenRouter API key for LLM access"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare Zone ID for chimney.beerpub.dev domain"
  type        = string
}

variable "critical_issue_numbers" {
  description = "List of critical path issue numbers to monitor"
  type        = list(number)
  default     = [525, 526, 527, 528]
}

variable "monitoring_thresholds" {
  description = "Pipeline monitoring thresholds"
  type = object({
    velocity_threshold    = number
    stale_threshold_hours = number
  })
  default = {
    velocity_threshold    = 3.0
    stale_threshold_hours = 6
  }
}

variable "deploy_ssh_public_key" {
  description = "SSH public key (OpenSSH format) for Hetzner mentisdb-prod server"
  type        = string
}

variable "beerpub_cloudflare_zone_id" {
  description = "Cloudflare zone ID for beerpub.dev — used for mem.beerpub.dev A record"
  type        = string
}
