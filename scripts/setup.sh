#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
node -e 'if (Number(process.versions.node.split(".")[0]) < 24) throw new Error("Node.js 24+ required for environment proxy support")'
if [[ ! -x modules/movist/.venv/bin/python ]]; then
  python3 -m venv modules/movist/.venv
fi
modules/movist/.venv/bin/python -m pip install --no-cache-dir --disable-pip-version-check --quiet -r modules/movist/requirements-cloud.txt
npm run build
npm run validate
modules/movist/.venv/bin/python -m unittest discover -s modules/movist -p 'test_*.py'
