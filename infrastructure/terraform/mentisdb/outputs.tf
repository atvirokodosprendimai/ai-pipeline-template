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

output "mentisdb_volume_id" {
  description = "Hetzner Volume ID holding the persistent /var/lib/mentisdb. Survives server delete/recreate. Protected by `delete_protection = true` + `lifecycle.prevent_destroy = true`."
  value       = hcloud_volume.mentisdb_data.id
}

output "mentisdb_volume_device" {
  description = "Linux device path the volume appears at on the server (use for fstab / mount commands)."
  value       = hcloud_volume.mentisdb_data.linux_device
}

output "mentisdb_curl_example" {
  description = "Working curl command for the protected API. Pull the password from MENTISDB_PASSWORD org secret or your password manager."
  value       = "curl -u mentisdb:$MENTISDB_PASSWORD -X POST -H 'Content-Type: application/json' -d '{}' https://${var.domain_name}/v1/agents"
}
