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
