# Terraform Outputs for AI Pipeline Infrastructure

output "repository_url" {
  description = "URL of the GitHub repository"
  value       = github_repository.wgmesh.html_url
}

output "dashboard_url" {
  description = "URL of the pipeline dashboard"
  value       = "https://chimney.beerpub.dev/pipeline"
}

output "critical_issues" {
  description = "List of critical path issues being monitored"
  value       = var.critical_issue_numbers
}

output "monitoring_config" {
  description = "Pipeline monitoring configuration"
  value = {
    velocity_threshold    = var.monitoring_thresholds.velocity_threshold
    stale_threshold_hours = var.monitoring_thresholds.stale_threshold_hours
  }
}

output "mentisdb_ipv4" {
  value = hcloud_server.mentisdb.ipv4_address
}

output "mentisdb_url" {
  value = "https://mem.beerpub.dev"
}

output "mentisdb_ssh" {
  value = "ssh root@${hcloud_server.mentisdb.ipv4_address}"
}
