# OpenTofu State Backend Bootstrap

This repository follows the org OpenTofu convention used by mailservice:
https://github.com/atvirokodosprendimai/mailservice/blob/main/docs/hetzner-cicd.md

The `pipeline` and `mentisdb` stacks use empty `backend "s3" {}` blocks.
Operators and CI generate `backend.hcl` at runtime, then run
`tofu init -backend-config=backend.hcl`.

## Tooling
Install OpenTofu locally:
```bash
brew install opentofu
```
Or download it from:
```text
https://opentofu.org/docs/intro/install/
```
CI uses `opentofu/setup-opentofu@v1` with `tofu_version: 1.8.5`.

## Required GitHub Secrets
Set these as org or repo secrets.

| Area | Secrets |
| --- | --- |
| State | `TOFU_STATE_BUCKET` |
| State | `TOFU_STATE_REGION=eu-central-1` |
| State | `TOFU_STATE_ENDPOINT=https://fsn1.your-objectstorage.com` |
| State | `TOFU_STATE_ACCESS_KEY` |
| State | `TOFU_STATE_SECRET_KEY` |
| Hetzner | `HCLOUD_API` |
| Hetzner | `HETZNER_SSH_PUBLIC_KEY` |
| Cloudflare | `BEERPUB_CLOUDFLARE_API_TOKEN` (zone-scoped to beerpub.dev) |
| Cloudflare | `CLOUDFLARE_ZONE_ID` |
| Cloudflare | `BEERPUB_CLOUDFLARE_ZONE_ID` |
| Pipeline | `PUSH_TOKEN` |
| Pipeline | `OPENROUTER_API_KEY` |

## One-Time Bucket Setup
Create a private Hetzner Object Storage bucket in the Hetzner Console:
```text
Project -> Object Storage -> Create Bucket
Region: fsn1
Privacy: Private
```
Set the bucket name in `TOFU_STATE_BUCKET`.

Alternatively, create it with the AWS CLI after S3 credentials exist:
```bash
export AWS_ACCESS_KEY_ID="<hetzner-object-storage-access-key>"
export AWS_SECRET_ACCESS_KEY="<hetzner-object-storage-secret-key>"

aws --endpoint-url https://fsn1.your-objectstorage.com \
  s3 mb "s3://${TOFU_STATE_BUCKET}"
```
Create Object Storage credentials in:
```text
Hetzner Cloud Console -> Project -> Security -> S3 Credentials
```
Save the secret key immediately. Hetzner does not show it again.

## State Layout
```text
<TOFU_STATE_BUCKET>/
|-- pipeline/terraform.tfstate
`-- mentisdb/terraform.tfstate
```

## Local Backend Config
Generate `backend.hcl` in the stack directory. The file is gitignored.

For `pipeline`:
```bash
cd infrastructure/terraform/pipeline
STATE_KEY="pipeline/terraform.tfstate"
```
For `mentisdb`:
```bash
cd infrastructure/terraform/mentisdb
STATE_KEY="mentisdb/terraform.tfstate"
```
Then generate backend config and initialize:
```bash
cat > backend.hcl <<EOF
bucket = "${TOFU_STATE_BUCKET}"
region = "${TOFU_STATE_REGION:-eu-central-1}"
endpoints = { s3 = "${TOFU_STATE_ENDPOINT:-https://fsn1.your-objectstorage.com}" }
key = "${STATE_KEY}"
access_key = "${TOFU_STATE_ACCESS_KEY}"
secret_key = "${TOFU_STATE_SECRET_KEY}"
skip_credentials_validation = true
skip_metadata_api_check     = true
skip_region_validation      = true
skip_requesting_account_id  = true
skip_s3_checksum            = true
use_path_style              = true
EOF

tofu init -backend-config=backend.hcl
```

## Local Pipeline Workflow
```bash
cd infrastructure/terraform/pipeline
export TF_VAR_github_push_token="<github-pat>"
export TF_VAR_openrouter_api_key="<openrouter-api-key>"
export TF_VAR_cloudflare_zone_id="<chimney-zone-id>"
export TF_VAR_cloudflare_api_token="<cloudflare-api-token>"

tofu plan
tofu apply
```

## Local MentisDB Workflow
```bash
cd infrastructure/terraform/mentisdb
export TF_VAR_hcloud_token="<hetzner-cloud-api-token>"
export TF_VAR_cloudflare_api_token="<cloudflare-api-token>"
export TF_VAR_deploy_ssh_public_key="ssh-ed25519 AAAA..."
export TF_VAR_beerpub_cloudflare_zone_id="<beerpub-zone-id>"

tofu plan
tofu apply
```

## CI Workflow
GitHub Actions generates `backend.hcl` per stack, runs
`tofu init -backend-config=backend.hcl`, then passes provider credentials
through `TF_VAR_*`. The GitHub provider reads `var.github_push_token`, the
Hetzner provider reads `var.hcloud_token`, and Cloudflare reads
`var.cloudflare_api_token`.

## Locking Note
Hetzner Object Storage does not provide DynamoDB-style state locking. Avoid
concurrent applies, and do not run local `tofu apply` while CI is applying.
