# Terraform Infrastructure

Terraform is split into isolated working directories so each stack has its own providers, variables, outputs, and state.

## Modules

- `pipeline/` manages the existing wgmesh GitHub repository plus the `chimney.beerpub.dev` pipeline dashboard DNS, page rule, and health alert file. The first run against existing infrastructure requires `terraform import` for pre-existing resources.
- `mentisdb/` provisions the new Hetzner VPS for MentisDB and the `mem.beerpub.dev` Cloudflare A record.

Each module is run independently from its own directory and has its own Terraform state.

## State Backend

Configured: both modules use Hetzner Object Storage at `fsn1` as an S3-compatible remote state backend. See [BOOTSTRAP.md](BOOTSTRAP.md) for one-time bucket, credential, GitHub secret, and local operator setup.
