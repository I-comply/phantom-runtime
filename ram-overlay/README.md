# RAM Overlay Engine

Mounts a tmpfs (`noexec,nosuid,nodev`, mode 0700) at `/mnt/ephemeral_ramdisk`; on exit/SIGTERM shreds files, unmounts, removes the mount point.

## Run
    ./run.sh                       # or: docker compose up --build

## Requirements
- `--cap-add SYS_ADMIN` (mount(2)); all other caps dropped.
- Hosts with AppArmor: `--security-opt apparmor=unconfined` (default profile denies mount).
- Do NOT use `--privileged`.

## Config
`SIZE_MB` (default 256), `MOUNT_POINT` (default `/mnt/ephemeral_ramdisk`).
