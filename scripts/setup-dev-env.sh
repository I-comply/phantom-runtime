#!/usr/bin/env bash
# Dev/CI-box bootstrap: world-readable Python 3.11 venv (sandboxed test runs drop privileges and cannot
# read a venv under /tmp/claude-0) and a pinned, checksum-verified k6 (not in apt).
# Usage: scripts/setup-dev-env.sh [venv_dir] [bin_dir]   (defaults: /opt/venv311, /usr/local/bin)
set -euo pipefail
VENV="${1:-/opt/venv311}"
BIN="${2:-/usr/local/bin}"
K6_VERSION="${K6_VERSION:-0.54.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REQ="$ROOT/phantom-runtime-main/backend/requirements.txt"

command -v uv >/dev/null || pip install -q uv
[ -x "$VENV/bin/python" ] || uv venv --python 3.11 "$VENV"
uv pip install -q --python "$VENV/bin/python" -r "$REQ" pytest httpx
chmod -R a+rX "$VENV"
# uv's interpreter may live under a private home; make its tree traversable.
PYHOME="$("$VENV/bin/python" -c 'import sys;print(sys.base_prefix)')"
chmod a+x "$(dirname "$PYHOME")" 2>/dev/null || true
chmod -R a+rX "$PYHOME" 2>/dev/null || true

if ! "$BIN/k6" version 2>/dev/null | grep -q "v$K6_VERSION"; then
  T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
  base="https://github.com/grafana/k6/releases/download/v$K6_VERSION"
  pkg="k6-v$K6_VERSION-linux-amd64"
  curl -fsSL -o "$T/$pkg.tar.gz" "$base/$pkg.tar.gz"
  curl -fsSL -o "$T/sums" "$base/k6-v$K6_VERSION-checksums.txt"
  (cd "$T" && grep " $pkg.tar.gz\$" sums | sha256sum -c -)
  tar -xzf "$T/$pkg.tar.gz" -C "$T"
  install -m 0755 "$T/$pkg/k6" "$BIN/k6"
fi
echo "venv: $VENV  k6: $("$BIN/k6" version)"
