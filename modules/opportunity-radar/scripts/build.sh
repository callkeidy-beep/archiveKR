#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
node "$root/scripts/build-worker.mjs"
rm -rf "$root/dist"
mkdir -p "$root/dist/server"
cp "$root/worker/index.js" "$root/dist/server/index.js"
if [[ -f "$root/.openai/hosting.json" ]]; then
  mkdir -p "$root/dist/.openai"
  cp "$root/.openai/hosting.json" "$root/dist/.openai/hosting.json"
fi
mkdir -p "$root/public"
cp "$root/app/index.html" "$root/public/index.html"
