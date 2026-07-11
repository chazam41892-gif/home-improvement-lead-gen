# Lead Gen Pro v3.1 — Standalone Lead Generation Platform

**Sell more home improvement jobs. Find qualified leads. Close deals. Repeat.**

Lead Gen Pro is a complete, self-hosted lead generation engine covering **44 home-service trades** across **8 discovery platforms** — with Stripe billing, CRM+ pipeline, AI enrichment, and native mobile/desktop apps. One `docker compose up` and you're live.

```bash
docker compose up --build
# Open http://localhost:8080
```

---

## Pricing

| Plan | Price | Leads/Month | Trades | Platforms | CRM Sync | Support |
|------|-------|-------------|--------|-----------|----------|---------|
| **Starter** | $97/mo | 500 | 10 core | 3 | Basic | Email |
| **Growth** | $197/mo | 2,000 | 25 | 5 | HubSpot | Priority |
| **Pro** | $497/mo | 10,000 | 44 | 8 | Multi-CRM | Dedicated |
| **Enterprise** | $997/mo | Unlimited | 44 | 8 | Custom | White-glove |

[Buy now →](https://growth.leviathansi.xyz) or self-host with your own keys.

---

## Quick Start

### Option A: Docker (recommended)
```bash
cp .env.example .env
# Edit .env with your API keys
docker compose up --build
```

### Option B: pip install
```bash
pip install leadgen-pro
cp .env.example .env
leadgen
```

### Option C: Deploy to your server
```bash
# Build & run in background
docker compose -f docker-compose.prod.yml up --build -d
```

---

## What You Get

### 44 Home-Service Trades
Plumbing, HVAC, electrical, roofing, landscaping, painting, concrete, masonry, siding, framing, glass, drywall, flooring, tile, finish carpentry, kitchen & bath remodel, deck & fence, gutter, window replacement, tree service, pool service, water damage restoration, fire restoration, mold removal, solar installation, water treatment, septic, well drilling, chimney, driveway paving, carpet cleaning, handyman, locksmith, security systems, fire protection, dumpster rental, demolition, appliance repair, garage door, pressure washing, and more.

### 8 Discovery Platforms
Google Maps, HomeAdvisor, Angi, Yelp, Facebook, Nextdoor, Instagram, Houzz

### Core Features
- **Natural language search** — Type "plumbers in Eugene, OR" and get qualified leads
- **Smart lead scoring** — Contact completeness, business presence, industry relevance, location match
- **Multi-source merge** — Combine Exa + Perplexity results with dedup
- **AI enrichment** — Auto-extract phone, email, website, employee count, revenue from search results
- **Beautiful dashboard** — Dark-theme UI with real-time stats, lead table, trade browser

### Billing & Conversion
- **Stripe integration** — Checkout Sessions, webhooks, billing portal, cancel-at-period-end
- **Lead-to-revenue pipeline** — Trade lead → account → payment → subscription
- **4 plans** — Starter ($97/mo), Growth ($197/mo), Pro ($497/mo), Enterprise ($997/mo)

### CRM+ Pipeline
- Smart routing: Search → Enrich → LLM Score → CRM Push → Nurture
- CRM sync (HubSpot, Salesforce, Pipedrive, Zoho, custom)
- Nurture engine with automated follow-up sequences
- Appointment scheduling widget

### Marketing Tools
- Landing page generator (custom colors, CTAs)
- Ad copy generation for Google, Facebook, Instagram
- UTM link builder
- Tracking pixel injection (Facebook, Google, TikTok, LinkedIn)

### Deployment
- **Docker** — Single command deploy, health-checked, auto-restart
- **pip install** — Install as a Python package, run anywhere
- **Security** — API key auth, CORS whitelist, rate limiting
- **Persistence** — JSONL flat-file storage, survives restarts
- **Android app** — Trade discovery, revenue dashboard, lead conversion
- **Tauri desktop** — Cross-platform desktop client

---

## API

| Endpoint | Description | Auth |
|----------|-------------|------|
| `GET /health` | Full system health | None |
| `POST /api/search/natural` | Natural language lead search | Bearer |
| `POST /api/search` | Structured search | Bearer |
| `POST /api/search/multi` | Multi-provider merge search | Bearer |
| `GET /api/leads` | Paginated lead list | Bearer |
| `POST /api/trades/discover` | Trade-specific business discovery | Bearer |
| `POST /api/trades/convert` | Lead → account → payment pipeline | Bearer |
| `POST /api/billing/*` | Stripe checkout, portal, subscription | Bearer |
| `POST /api/billing/webhook` | Stripe webhook (signature verified) | None |
| `POST /api/capture/lead` | Public lead capture form | None |

Full API docs at `/docs` (Swagger UI).

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `EXA_API_KEY` | For search | Exa AI search provider (1000 free/mo) |
| `PERPLEXITY_API_KEY` | Optional | Perplexity AI search provider |
| `API_KEY` | For auth | Enables bearer token auth on all endpoints |
| `STRIPE_SECRET_KEY` | For billing | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | For billing | Stripe webhook signing secret |
| `STRIPE_PRICE_STARTER` | For billing | Stripe price ID for Starter plan |
| `CORS_ORIGINS` | Optional | Comma-separated allowed origins |

---

## Architecture

```
User → Dashboard (HTML/JS) or Mobile/Desktop App
                        ↓
               FastAPI (main.py) — :8080
                  /    |    \
      Engine        CRM+      Stripe
    (scout.py)   (routes)   (integration)
        |            |           |
   Search       Pipeline     Payments
   Providers    Routing      Subscriptions
   (Exa,        Nurture
    Perplexity) Analytics
        |
    44 Trades × 8 Platforms
        |
   Scoring + Conversion
```

---

## Install as Python Package

```bash
pip install leadgen-pro
leadgen
# → http://localhost:8080
```

Or from source:
```bash
git clone https://github.com/chazam41892-gif/home-improvement-lead-gen.git
cd home-improvement-lead-gen
pip install -e .
python run.py
```

---

## Run Tests

```bash
python run_tests.py
# or
python smoke_test.py
```

---

## License

MIT License — Metanoia Unlimited LLC. Built for production. Self-hosted. Bring your own keys.

**Sold as a standalone product.** The lead generation module is a self-contained, sellable unit — independent of the Leviathan swarm, Gambot IDE, or any other Metanoia project. It ships with its own Docker config, pip package, API, dashboard, and billing.
