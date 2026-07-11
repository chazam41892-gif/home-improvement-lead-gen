#!/usr/bin/env bash
set -euo pipefail

DOMAIN="growth.leviathansi.xyz"
REPO="https://github.com/chazam41892-gif/home-improvement-lead-gen.git"
DIR="/opt/leadforge"

echo "╔══════════════════════════════════════════════╗"
echo "║        LeadForge — One-Click Deploy         ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# --- Prerequisites ---
if [ "$EUID" -ne 0 ]; then echo "Run as root: sudo bash deploy.sh"; exit 1; fi

if ! command -v docker &>/dev/null; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi

if ! command -v git &>/dev/null; then
  apt-get update && apt-get install -y git
fi

# --- Clone ---
echo "Cloning LeadForge..."
rm -rf "$DIR"
git clone "$REPO" "$DIR"
cd "$DIR/deploy"

# --- SSL ---
echo "Obtaining SSL certificate for $DOMAIN..."
mkdir -p /var/www/certbot
docker run --rm -p 80:80 \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  certbot/certbot certonly --standalone \
  -d "$DOMAIN" --agree-tos --non-interactive \
  --email admin@"$DOMAIN" || echo "SSL failed — run certbot manually later"

# --- Start ---
echo "Starting stack..."
docker compose up -d --build

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  LeadForge is LIVE at https://$DOMAIN  ║"
echo "║                                              ║"
echo "║  First user who registers becomes owner      ║"
echo "║  Open the URL and create your account        ║"
echo "╚══════════════════════════════════════════════╝"
