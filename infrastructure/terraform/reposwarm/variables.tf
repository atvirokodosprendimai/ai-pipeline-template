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
  description = "Cloudflare zone ID for beerpub.dev"
  type        = string
}

variable "domain_name" {
  description = "Public domain for RepoSwarm UI"
  type        = string
  default     = "swarm.beerpub.dev"
}

variable "letsencrypt_email" {
  description = "Email for Let's Encrypt registration"
  type        = string
  default     = "admin@beerpub.dev"
}

variable "reposwarm_api_token" {
  description = "RepoSwarm API token for authentication"
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key for RepoSwarm worker"
  type        = string
  sensitive   = true
  default     = ""
}

variable "openrouter_api_key" {
  description = "OpenRouter API key for RepoSwarm worker (LiteLLM proxy mode)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "llm_provider" {
  description = "LLM provider: anthropic or openrouter"
  type        = string
  default     = "openrouter"
}

variable "github_token" {
  description = "GitHub token for RepoSwarm to access repos"
  type        = string
  sensitive   = true
}
