# Terraform Infrastructure as Code for AI Pipeline
# Manages GitHub repository, workflows, and monitoring

terraform {
  required_version = ">= 1.9.0"

  backend "s3" {
    bucket = "atvirokodosprendimai-tfstate"
    key    = "pipeline/terraform.tfstate"
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
    github = {
      source  = "integrations/github"
      version = "~> 5.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

provider "github" {
  owner = "atvirokodosprendimai"
}

provider "cloudflare" {
  # Configure via environment variables
  # CLOUDFLARE_API_TOKEN
}

# GitHub Repository
resource "github_repository" "wgmesh" {
  name         = "wgmesh"
  description  = "Zero-infrastructure anycast CDN built on WireGuard mesh"
  visibility   = "public"
  has_issues   = true
  has_projects = false
  has_wiki     = false
}

# Repository Labels
resource "github_issue_label" "critical" {
  repository  = github_repository.wgmesh.name
  name        = "critical"
  color       = "e11d21"
  description = "Critical path to first customer"
}

resource "github_issue_label" "copilot-triaging" {
  repository  = github_repository.wgmesh.name
  name        = "copilot-triaging"
  color       = "fbca04"
  description = "Issue being triaged by Copilot"
}

# Repository Variables
resource "github_actions_variable" "push_token" {
  repository    = github_repository.wgmesh.name
  variable_name = "PUSH_TOKEN"
  value         = var.github_push_token
}

resource "github_actions_variable" "openrouter_key" {
  repository    = github_repository.wgmesh.name
  variable_name = "OPENROUTER_API_KEY"
  value         = var.openrouter_api_key
}

# Cloudflare DNS for Dashboard
resource "cloudflare_record" "dashboard" {
  zone_id = var.cloudflare_zone_id
  name    = "pipeline"
  value   = "wgmesh-agent-pipeline-dashboard.pages.dev"
  type    = "CNAME"
  ttl     = 3600
  proxied = true
}

# Cloudflare Page Rule for Dashboard
resource "cloudflare_page_rule" "dashboard_redirect" {
  zone_id = var.cloudflare_zone_id
  target  = "chimney.beerpub.dev/pipeline*"
  actions {
    forwarding_url {
      url         = "https://wgmesh-agent-pipeline-dashboard.pages.dev/"
      status_code = 301
    }
  }
}

# Monitoring Alerts
resource "github_repository_file" "pipeline_health_alert" {
  repository = github_repository.wgmesh.name
  branch     = "main"
  file       = ".github/alerts/pipeline-health.json"
  content = jsonencode({
    "critical_issues" = [525, 526, 527, 528],
    "monitoring" = {
      "velocity_threshold"    = 3.0,
      "stale_threshold_hours" = 6
    }
  })
  commit_message      = "Add pipeline health monitoring configuration"
  commit_author       = "Terraform"
  commit_email        = "terraform@example.com"
  overwrite_on_create = true
}
