#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m unittest discover -s tests
python3 -m atl demo
python3 -m unittest bakeoff.suite
python3 -m harness.run_agents --tenants 2 --agents 4 --out "$(mktemp -d)" >/dev/null
