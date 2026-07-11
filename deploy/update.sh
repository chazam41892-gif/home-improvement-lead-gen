#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=== Updating leadgen stack ==="

git pull

sudo docker compose build
sudo docker compose up -d

sudo docker system prune -f

echo "=== Update complete ==="
