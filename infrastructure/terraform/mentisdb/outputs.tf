output "mentisdb_ipv4" {
  value = hcloud_server.mentisdb.ipv4_address
}

output "mentisdb_url" {
  value = "https://mem.beerpub.dev"
}

output "mentisdb_ssh" {
  value = "ssh root@${hcloud_server.mentisdb.ipv4_address}"
}
