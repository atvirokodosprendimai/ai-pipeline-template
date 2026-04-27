output "mentisdb_ipv4" {
  value = hcloud_server.mentisdb.ipv4_address
}

output "mentisdb_url" {
  value = "https://mem.beerpub.dev"
}

output "mentisdb_ssh" {
  value = "ssh root@${hcloud_server.mentisdb.ipv4_address}"
}

output "mentisdb_ssh_private_key" {
  description = "Ephemeral SSH private key for mentisdb-prod debug access (regenerated on every apply that recreates tls_private_key.deploy). Sensitive — extract via `tofu output -raw mentisdb_ssh_private_key > /tmp/key && chmod 600 /tmp/key`."
  value       = tls_private_key.deploy.private_key_openssh
  sensitive   = true
}

output "mentisdb_basic_auth_password" {
  description = "Random password for mentisdb HTTP Basic Auth (user: mentisdb). Pair with username 'mentisdb' for Authorization: Basic header. Rotate via `tofu apply -replace=random_password.basic_auth`."
  value       = random_password.basic_auth.result
  sensitive   = true
}

output "mentisdb_curl_example" {
  description = "Working curl command for the protected API"
  value       = "curl -u mentisdb:<password> -X POST -H 'Content-Type: application/json' -d '{}' https://${var.domain_name}/v1/agents"
}
