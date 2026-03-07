#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

docker build -f docker/build-centos7-sender.Dockerfile -t screen-airdrop-centos7-builder .
CID=$(docker create screen-airdrop-centos7-builder)
mkdir -p dist
# shellcheck disable=SC2086
docker cp "$CID":/work/dist/screen-airdrop-sender-legacy-centos7-x86_64 dist/
docker rm "$CID" >/dev/null

echo "CentOS7 sender binary exported to dist/"
