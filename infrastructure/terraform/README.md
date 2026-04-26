# Terraform Infrastructure

Terraform is split into isolated working directories so each stack has its own providers, variables, outputs, and state.

## Modules

- `pipeline/` manages the existing wgmesh GitHub repository plus the `chimney.beerpub.dev` pipeline dashboard DNS, page rule, and health alert file. The first run against existing infrastructure requires `terraform import` for pre-existing resources.
- `mentisdb/` provisions the new Hetzner VPS for MentisDB and the `mem.beerpub.dev` Cloudflare A record.

Each module is run independently from its own directory and has its own Terraform state.

## State Backend

No remote backend is configured yet. Each module currently uses local state, which is fine for a one-shot operator apply but problematic for CI auto-apply.

TODO: add an S3-compatible backend, such as Hetzner Object Storage, before relying on CI auto-apply.
