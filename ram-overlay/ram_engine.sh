#!/usr/bin/env bash
set -euo pipefail
MOUNT_POINT="${MOUNT_POINT:-/mnt/ephemeral_ramdisk}"
SIZE_MB="${SIZE_MB:-256}"
cleanup() {
    trap - EXIT INT TERM
    if mountpoint -q "${MOUNT_POINT}"; then
        find "${MOUNT_POINT}" -type f -exec shred -u -z -n 1 {} + 2>/dev/null || true
        umount "${MOUNT_POINT}" || umount -l "${MOUNT_POINT}" || true
    fi
    rmdir "${MOUNT_POINT}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
mkdir -p "${MOUNT_POINT}"
mount -t tmpfs -o "size=${SIZE_MB}M,mode=0700,noexec,nosuid,nodev" tmpfs "${MOUNT_POINT}"
echo "STATE_CHECK_ACTIVE" > "${MOUNT_POINT}/runtime.lock"
sync
while true; do sleep 3 & wait $!; done
