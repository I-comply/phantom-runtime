#!/usr/bin/env bash
# Local SAST + dependency audit; stand-in for Semgrep Guardian.
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -q bandit pip-audit
echo "== bandit (SAST)"
bandit -q -r . -x ./test_all.py,./scripts
echo "== pip-audit (dependencies)"
pip-audit -r requirements.txt
echo "== pytest"
python -m pytest -q
