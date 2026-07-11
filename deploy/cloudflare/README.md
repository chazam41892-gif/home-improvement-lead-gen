# Cloudflare Tunnel Deployment — Lead Gen Pro

Deploy Lead Gen Pro behind `growth.leviathansi.xyz` using Cloudflare Tunnel.
This avoids opening firewall ports and gives you Cloudflare-managed TLS, DDoS
protection, and DNS without managing certificates on the host.

## Requirements

- A machine that can run Docker (Linux server, NAS, local desktop, or VM).
- Cloudflare account with `growth.leviathansi.xyz` added as a site.
- `.env` file in the project root with production secrets.

## Quick start

### 1. Prepare the host

Install Docker + Docker Compose on the host. Copy the repo to the host or
clone it:

```bash
git clone https://github.com/chazam41892-gif/home-improvement-lead-gen.git
cd home-improvement-lead-gen
```

### 2. Create the tunnel

On the host (Linux/macOS):

```bash
cd deploy/cloudflare
bash scripts/setup-tunnel.sh
```

This will:
- Install `cloudflared`
- Create a tunnel named `leadgen-growth`
- Route `growth.leviathansi.xyz` to that tunnel
- Print a `TUNNEL_TOKEN` for your `.env`

On Windows hosts, install `cloudflared` manually from
https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
and run these commands in an admin PowerShell or WSL:

```bash
cloudflared tunnel login
cloudflared tunnel create leadgen-growth
cloudflared tunnel route dns <TUNNEL_ID> growth.leviathansi.xyz
cloudflared tunnel token <TUNNEL_ID>
```

### 3. Add the token to `.env`

In the project root `.env`:

```env
TUNNEL_TOKEN=<paste token here>
```

### 4. Start the stack

```bash
cd deploy/cloudflare
docker compose up -d
```

The app is now live at `https://growth.leviathansi.xyz`.

## What the compose file does

- `leadgen` — builds and runs the FastAPI app from the repo root `Dockerfile`.
- `cloudflared` — connects the tunnel to Cloudflare and routes HTTPS traffic to
  the `leadgen` container on port 8080.

## Updating

To deploy a new version:

```bash
cd deploy/cloudflare
docker compose pull  # if using a registry image
docker compose up -d --build
```

## Useful commands

```bash
docker compose logs -f leadgen
docker compose logs -f cloudflared
cloudflared tunnel list
```

## Troubleshooting

- Tunnel not connecting? Check `TUNNEL_TOKEN` is set correctly and restart
  `cloudflared`.
- DNS not resolving? Ensure `growth.leviathansi.xyz` DNS is proxied (orange
  cloud) in the Cloudflare dashboard.
- App returns 502? Verify the `leadgen` container is healthy:
  `docker compose ps`.
