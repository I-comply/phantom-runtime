#!/usr/bin/env bash
# Local SAST + dependency audit; stand-in for Semgrep Guardian.
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -q -r requirements.txt bandit pip-audit
echo "== bandit (SAST, medium+ severity fails)"
bandit -q -r . -ll -x ./test_all.py,./test_feeds.py,./scripts
echo "== pip-audit (dependencies)"
pip-audit -r requirements.txt
echo "== pytest"
python -m pytest -q
