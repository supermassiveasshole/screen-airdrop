#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <wheelhouse-dir>"
  exit 1
fi

WHEELHOUSE="$1"
python -m pip install --no-index --find-links "$WHEELHOUSE" screen-airdrop
