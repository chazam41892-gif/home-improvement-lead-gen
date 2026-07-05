# LEAD GEN PRO v3.1 — Production-Grade Lead Generation Platform

The complete, self-hosted lead generation engine with **44 home-service trades**, 
multi-platform discovery, Stripe billing, CRM+ pipeline, and native mobile/desktop apps.

```bash
docker compose up --build
# Open http://localhost:8080
```

---

## Quick Start

### Option A: Docker (recommended)
```bash
# 1. Copy env template
cp .env.example .env
# Edit .env with your API keys

# 2. Start
docker compose up --build
```

### Option B: Local Python
```bash
pip install -r requirements.txt
python run.py
```

### Option C: Deploy to server
```bash
# Build & run in background
docker compose up --build -d
```

---

## What You Get

### Core Features
- **44 trades** — Plumbing, HVAC, electrical, roofing, landscaping, painting, concrete, masonry, solar, tree service, chimney, garage door, locksmith, drywall, flooring, and 30+ more
- **8 discovery platforms** — Google Maps, HomeAdvisor, Angi, Yelp, Facebook, Nextdoor, Instagram, Houzz
- **Smart lead scoring** — Contact completeness, business presence, industry relevance, location match, enrichment potential
- **Natural language search** — Type "plumbers in Eugene, OR" and get qualified leads
- **Chat dashboard** — Beautiful dark-theme UI with real-time stats
- **Multi-source merge** — Combine Exa + Perplexity results with dedup

### Billing & Conversion
- **Stripe integration** — Checkout Sessions, webhooks, billing portal, cancel-at-period-end
- **Lead-to-revenue pipeline** — Trade lead → account → payment → subscription
- **4 plans** — Starter ($97/mo), Growth ($197/mo), Pro ($497/mo), Enterprise ($997/mo)

### CRM+ Pipeline
- Smart routing with 5 pipeline steps: Search → Enrich → LLM Score → CRM Push → Nurture
- CRM sync (HubSpot, Salesforce, custom)
- Nurture engine with automated follow-up sequences
- Appointment scheduling widget

### Deployment
- **Docker** — Single command deploy, health-checked, auto-restart
- **Security** — Optional API key auth (set `API_KEY` env var), CORS whitelist, rate limiting
- **Persistence** — All data persisted to `data/` directory (JSONL), survives restarts
- **Android app** — Trade discovery, revenue dashboard, lead conversion screens
- **Tauri desktop** — Cross-platform desktop client with trade endpoints

### Marketing Tools
- Landing page generator (custom colors, CTAs)
- Ad copy generation for multiple platforms
- UTM link builder
- Tracking pixel injection (Facebook, Google, TikTok, LinkedIn)

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
| `POST /api/billing/webhook` | Stripe webhook (no auth — signature verified) | None |
| `POST /api/capture/lead` | Public lead capture form | None |

Full API docs at `/docs` (Swagger UI).

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `EXA_API_KEY` | For search | Exa AI search provider (1000 free/mo) |
| `PERPLEXITY_API_KEY` | Optional | Perplexity AI search provider |
| `API_KEY` | For auth | Enables bearer token auth on all API endpoints |
| `STRIPE_SECRET_KEY` | For billing | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | For billing | Stripe webhook signing secret |
| `STRIPE_PRICE_STARTER` | For billing | Stripe price ID for Starter plan |
| `CORS_ORIGINS` | Optional | Comma-separated allowed origins |

---

## Run Tests

```bash
python run_tests.py
```

---

## Native Apps

### Android
Location: `android/` — Android Studio project with 3 trade screens.

### Tauri Desktop
```bash
cd desktop && npm install && npm run tauri dev
```

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

## License

Metanoia Unlimited LLC — HaChazal

Built for production. Self-hosted. Bring your own keys.
