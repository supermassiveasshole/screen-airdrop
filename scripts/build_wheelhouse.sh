#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python -m build
mkdir -p dist/wheelhouse
python -m pip download --dest dist/wheelhouse "./dist/$(ls dist | grep '\\.whl$' | head -n1)" || true

echo "Built artifacts under dist/"
