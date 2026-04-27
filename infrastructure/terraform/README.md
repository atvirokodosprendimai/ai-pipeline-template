# OpenTofu Infrastructure

OpenTofu is split into isolated working directories so each stack has its own providers, variables, outputs, and state.

## Modules

- `pipeline/` manages the existing wgmesh GitHub repository plus the `chimney.beerpub.dev` pipeline dashboard DNS, page rule, and health alert file. The first run against existing infrastructure requires `tofu import` for pre-existing resources.
- `mentisdb/` provisions the new Hetzner VPS for MentisDB and the `mem.beerpub.dev` Cloudflare A record.

Each module is run independently from its own directory and has its own OpenTofu state.

## State Backend

Both modules use an empty `backend "s3" {}` block. Generate a gitignored `backend.hcl` at init time and run `tofu init -backend-config=backend.hcl` from the module directory.

See [BOOTSTRAP.md](BOOTSTRAP.md) for one-time bucket, credential, GitHub secret, and local operator setup.
