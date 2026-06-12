#!/usr/bin/env bash
set -euo pipefail

SHA=$(cat /etc/wgmesh-pipeline/deployed_sha)
IMAGE_OWNER=${GHCR_IMAGE_OWNER:-atvirokodosprendimai}

exec docker run --rm \
  --env-file /etc/wgmesh-pipeline/env \
  -v /opt/wgmesh-checkout:/opt/wgmesh-checkout \
  -v /var/cache/go-mod:/go/pkg/mod \
  --name wgmesh-pipeline \
  "ghcr.io/${IMAGE_OWNER}/wgmesh-pipeline:${SHA}"
