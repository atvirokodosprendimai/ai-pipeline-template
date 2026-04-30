output "server_ipv4" {
  value = hcloud_server.reposwarm.ipv4_address
}

output "domain" {
  value = var.domain_name
}

output "api_url" {
  value = "https://${var.domain_name}/v1"
}
