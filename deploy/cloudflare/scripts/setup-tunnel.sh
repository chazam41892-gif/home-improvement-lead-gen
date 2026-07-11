#!/usr/bin/env bash
# Cloudflare Tunnel setup for growth.leviathansi.xyz
# Run this on the host that will run the Lead Gen Pro Docker container.
set -e

DOMAIN="${DOMAIN:-growth.leviathansi.xyz}"
TUNNEL_NAME="${TUNNEL_NAME:-leadgen-growth}"

echo "=== Cloudflare Tunnel setup for ${DOMAIN} ==="

# 1. Install cloudflared if missing
if ! command -v cloudflared &> /dev/null; then
    echo "Installing cloudflared..."
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Debian/Ubuntu
        if command -v apt-get &> /dev/null; then
            curl -L --output /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
            sudo dpkg -i /tmp/cloudflared.deb || sudo apt-get install -f -y
        else
            curl -L --output /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
            chmod +x /tmp/cloudflared
            sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew install cloudflared
    else
        echo "Unsupported OS. Install cloudflared manually: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
        exit 1
    fi
fi

# 2. Authenticate (opens browser)
echo "Authenticating with Cloudflare..."
cloudflared tunnel login

# 3. Create tunnel
TUNNEL_ID=$(cloudflared tunnel create "$TUNNEL_NAME" | grep -oP 'id [^ ]+' | awk '{print $2}' || true)
if [ -z "$TUNNEL_ID" ]; then
    echo "Failed to create tunnel or tunnel already exists. Listing existing tunnels:"
    cloudflared tunnel list
    echo "Set TUNNEL_TOKEN in .env to the token of the existing tunnel."
    exit 1
fi

echo "Created tunnel: ${TUNNEL_ID}"

# 4. Route DNS
cloudflared tunnel route dns "$TUNNEL_ID" "$DOMAIN"

# 5. Get token
TUNNEL_TOKEN=$(cloudflared tunnel token "$TUNNEL_ID")

echo ""
echo "=== Add this to your .env file ==="
echo "TUNNEL_TOKEN=${TUNNEL_TOKEN}"
echo ""
echo "Then run:"
echo "  cd deploy/cloudflare"
echo "  docker compose up -d"
