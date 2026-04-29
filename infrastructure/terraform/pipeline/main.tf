# OpenTofu Infrastructure as Code for AI Pipeline
# Manages GitHub repository, workflows, and monitoring

terraform {
  required_version = ">= 1.8.0"

  backend "s3" {}

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
  token = var.github_push_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# GitHub Repository
resource "github_repository" "wgmesh" {
  name         = "wgmesh"
  description  = "Zero-infrastructure anycast CDN built on WireGuard mesh"
  visibility   = "public"
  has_issues   = true
  has_projects = false
  has_wiki     = false

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [description, homepage_url]
  }
}

import {
  to = github_repository.wgmesh
  id = "wgmesh"
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

# Repository Secrets
# NOTE: If the previous github_actions_variable.push_token / .openrouter_key
# were ever applied, the values were exposed in plaintext via the GitHub UI
# and Actions logs. Rotate both credentials before applying this change.
resource "github_actions_secret" "push_token" {
  repository      = github_repository.wgmesh.name
  secret_name     = "PUSH_TOKEN"
  plaintext_value = var.github_push_token
}

resource "github_actions_secret" "openrouter_key" {
  repository      = github_repository.wgmesh.name
  secret_name     = "OPENROUTER_API_KEY"
  plaintext_value = var.openrouter_api_key
}

# Cloudflare DNS for Dashboard
resource "cloudflare_record" "dashboard" {
  zone_id = var.cloudflare_zone_id
  name    = "pipeline"
  value   = "wgmesh-agent-pipeline-dashboard.pages.dev"
  type    = "CNAME"
  ttl     = 1
  proxied = true
}

# Cloudflare Page Rule for Dashboard
# TODO: Uncomment when Cloudflare API token has Page Rules:Edit permission (error 9109)
# resource "cloudflare_page_rule" "dashboard_redirect" {
#   zone_id = var.cloudflare_zone_id
#   target  = "chimney.beerpub.dev/pipeline*"
#   actions {
#     forwarding_url {
#       url         = "https://wgmesh-agent-pipeline-dashboard.pages.dev/"
#       status_code = 301
#     }
#   }
# }

# Monitoring Alerts
resource "github_repository_file" "pipeline_health_alert" {
  repository = github_repository.wgmesh.name
  branch     = "main"
  file       = ".github/alerts/pipeline-health.json"
  content = jsonencode({
    "critical_issues" = var.critical_issue_numbers,
    "monitoring" = {
      "velocity_threshold"    = var.monitoring_thresholds.velocity_threshold,
      "stale_threshold_hours" = var.monitoring_thresholds.stale_threshold_hours
    }
  })
  commit_message      = "Add pipeline health monitoring configuration"
  commit_author       = "Terraform"
  commit_email        = "terraform@example.com"
  overwrite_on_create = true
}
