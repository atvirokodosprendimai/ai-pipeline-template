# Terraform State Backend Bootstrap

This guide covers the one-time setup for the shared Terraform state backend used by the `pipeline` and `mentisdb` modules.

## Prerequisites

- Hetzner Cloud project access with permission to create Object Storage buckets and S3 credentials.
- GitHub permissions to create repository or organization secrets for `ai-pipeline-template`.
- Terraform 1.9.x locally if you plan to initialize or migrate state from your workstation.

## Backend

- Provider: Hetzner Object Storage, S3-compatible API.
- Region: `fsn1` (Falkenstein).
- Endpoint: `https://fsn1.your-objectstorage.com`.
- Bucket: `atvirokodosprendimai-tfstate`.
- Auth: S3 access key and secret key from Hetzner Cloud Project -> Security -> S3 Credentials.

## One-time bootstrap

1. Create the bucket in Hetzner Cloud Console:

   Project -> Object Storage -> Create Bucket -> Region `fsn1` -> Name `atvirokodosprendimai-tfstate` -> Privacy Public OFF (Private) -> Create.

   Or create it with the AWS CLI after S3 credentials exist:

   ```bash
   aws --endpoint-url https://fsn1.your-objectstorage.com s3 mb s3://atvirokodosprendimai-tfstate
   ```

2. Create S3 credentials:

   Hetzner Cloud Console -> Project -> Security -> S3 Credentials -> Create.

   Save the access key and secret key immediately. The secret key cannot be retrieved later.

3. Set GitHub secrets:

   Organization-level secrets are recommended for `ai-pipeline-template`.

   ```bash
   gh secret set HETZNER_S3_ACCESS_KEY --org atvirokodosprendimai --visibility selected --repos ai-pipeline-template
   gh secret set HETZNER_S3_SECRET_KEY --org atvirokodosprendimai --visibility selected --repos ai-pipeline-template
   ```

4. Set local operator credentials:

   ```bash
   export AWS_ACCESS_KEY_ID=<hetzner-s3-access-key>
   export AWS_SECRET_ACCESS_KEY=<hetzner-s3-secret-key>
   ```

5. Initialize each module:

   ```bash
   cd infrastructure/terraform/pipeline
   terraform init

   cd ../mentisdb
   terraform init
   ```

   The first init for each module creates its state file in the bucket under that module's configured state key.

## State file layout

```text
atvirokodosprendimai-tfstate/
|-- pipeline/terraform.tfstate
`-- mentisdb/terraform.tfstate
```

## Migrating from local state

If a module already has a local `terraform.tfstate`, run migration after adding the backend block:

```bash
cd infrastructure/terraform/pipeline
terraform init -migrate-state

cd ../mentisdb
terraform init -migrate-state
```

Terraform will upload the existing local state to the configured object storage key:

- `pipeline/terraform.tfstate`
- `mentisdb/terraform.tfstate`

Skip migration for modules that do not have local state yet.

## Locking note

Hetzner Object Storage does not support DynamoDB-style Terraform state locking. Concurrent applies are unsafe.

Current mitigations:

- Keep CI on the default single workflow runner pattern for this repository's low apply volume.
- Operators avoid running `terraform apply` locally while CI is running.
- Use `terraform plan` locally before any operator apply.

Future options if multi-operator applies become routine:

- Move state and applies to Terraform Cloud.
- Run a self-hosted Atlantis or similar apply coordinator.
- Add an external lock service around CI and local operator workflows.
