#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
.venv/bin/python -m pip download --only-binary=:all: --disable-pip-version-check -r requirements.lock --dest wheels
