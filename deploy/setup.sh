#!/usr/bin/env bash
set -euo pipefail

DOMAIN="growth.leviathansi.xyz"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Setup: $DOMAIN ==="

# --- Docker ---
if ! command -v docker &>/dev/null; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
fi

if ! command -v docker-compose &>/dev/null && ! docker compose version &>/dev/null; then
  echo "Installing Docker Compose..."
  sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# --- Directories ---
sudo mkdir -p /etc/letsencrypt /var/www/certbot

# --- SSL (staging first, then prod) ---
if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
  echo "Obtaining SSL certificate for $DOMAIN..."
  sudo docker run --rm -it \
    -v /etc/letsencrypt:/etc/letsencrypt \
    -v /var/www/certbot:/var/www/certbot \
    certbot/certbot certonly --webroot -w /var/www/certbot \
    -d "$DOMAIN" --agree-tos --non-interactive \
    --staging || true
  echo "If staging succeeded, re-run without --staging for real certs."
fi

# --- Start stack ---
cd "$DIR"
sudo docker compose up -d

echo ""
echo "=== Done ==="
echo "URL: https://$DOMAIN"
echo "To check logs: sudo docker compose logs -f"
