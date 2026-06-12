#!/usr/bin/env bash
set -euo pipefail

# Exact image ref is written by deploy-pipeline-box.yml at deploy time so the
# unit and the workflow can never diverge on owner/name; the SHA-file path is
# the fallback for hand-rolled deploys.
STATE_DIR=/etc/wgmesh-pipeline
if [ -f "$STATE_DIR/image_ref" ]; then
  IMAGE_REF=$(cat "$STATE_DIR/image_ref")
else
  SHA=$(cat "$STATE_DIR/deployed_sha")
  IMAGE_OWNER=${GHCR_IMAGE_OWNER:-atvirokodosprendimai}
  IMAGE_REF="ghcr.io/${IMAGE_OWNER}/wgmesh-pipeline:${SHA}"
fi

exec docker run --rm \
  --env-file "$STATE_DIR/env" \
  -v /opt/wgmesh-checkout:/opt/wgmesh-checkout \
  -v /var/cache/go-mod:/go/pkg/mod \
  --name wgmesh-pipeline \
  "$IMAGE_REF"
