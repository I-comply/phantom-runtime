#!/usr/bin/env bash
# Archives the PRIVATE tier (gitignored) so it can be moved to a private repository or encrypted storage.
# Usage: bash scripts/export-private.sh [output.tar.gz]   (default: private-export/pwx-private-<date>.tar.gz)
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:-private-export/pwx-private-$(date +%Y%m%d).tar.gz}"
mkdir -p "$(dirname "$out")"
tar -czf "$out" private
sha256sum "$out"
echo "Written to $out. This archive contains confidential material: do not commit it to a public repository."
