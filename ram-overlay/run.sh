#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
IMAGE="${IMAGE:-ram-overlay:latest}"
docker build -f Dockerfile.ram -t "${IMAGE}" .
exec docker run --rm --name ram-overlay \
  --cap-drop ALL --cap-add SYS_ADMIN \
  --security-opt no-new-privileges:true --security-opt apparmor=unconfined \
  --read-only -e SIZE_MB="${SIZE_MB:-256}" \
  "${IMAGE}"
