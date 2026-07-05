#!/usr/bin/env bash
set -euo pipefail

DEPLOY_HOST="${1:-${DEPLOY_HOST:-}}"
if [ -z "$DEPLOY_HOST" ]; then
  echo "ERROR: Usage: $0 <user@host>   or   DEPLOY_HOST=user@host $0"
  exit 1
fi

REMOTE_DIR="/opt/leadgen"
IMAGE="leadgen:latest"
TARBALL="leadgen.tar"
FILES=("$TARBALL" "docker-compose.prod.yml" ".env")

echo "==> Building Docker image: $IMAGE"
docker build -t "$IMAGE" .

echo "==> Saving image to $TARBALL"
docker save "$IMAGE" -o "$TARBALL"

echo "==> Creating remote directory $REMOTE_DIR on $DEPLOY_HOST"
ssh "$DEPLOY_HOST" "mkdir -p $REMOTE_DIR"

echo "==> Copying files to $DEPLOY_HOST:$REMOTE_DIR"
scp "${FILES[@]}" "$DEPLOY_HOST:$REMOTE_DIR/"

echo "==> Loading image and restarting on $DEPLOY_HOST"
ssh "$DEPLOY_HOST" "cd $REMOTE_DIR && docker load -i $TARBALL && docker compose -f docker-compose.prod.yml up -d"

echo "==> Cleaning up old Docker resources on $DEPLOY_HOST"
ssh "$DEPLOY_HOST" "docker system prune -f"

echo "==> Cleaning up local tarball"
rm -f "$TARBALL"

echo ""
echo "=== Deploy complete ==="
echo "    http://${DEPLOY_HOST#*@}:8080"
