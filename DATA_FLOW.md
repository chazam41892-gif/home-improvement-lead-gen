# Data Flow — Lead Gen Pro

## JSONL Files in `data/`

| File | Stores | Persistence |
|------|--------|-------------|
| `data/leads.jsonl` | Raw leads from scout/search (industry-agnostic) | Disk — survives restart |
| `data/trade_leads.jsonl` | Trade-specific leads from `ConversionPipeline` | Disk — survives restart |
| `data/trade_accounts.jsonl` | Converted accounts (lead → customer) | Disk — survives restart |
| `data/trade_payments.jsonl` | Payment records per account | Disk — survives restart |
| `data/trade_discovery_*.json` | Batch discovery snapshots from `seed_trades.py` | Disk — survives restart |
| `data/naics.csv` | NAICS industry codes for trade classification | Static reference |

In-memory state (`TradeLeadDiscovery._results`, `ConversionPipeline` instances) is **ephemeral** — lost on restart. Only data written to JSONL persists.

## Lead Lifecycle

```
                  ┌──────────────┐
                  │   Internet   │
                  │  (web crawl) │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │  Search /    │
                  │  Scout       │  ← Exa, Perplexity
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
    ┌─────────────│ Trade Lead   │
    │             │ Discovery    │  ← 44 trades × 8 platforms
    │             └──────┬───────┘
    │                    │
    │                    ▼
    │             ┌──────────────┐
    │             │   Scoring    │  ← LLM-based (Anthropic/CometAPI)
    │             └──────┬───────┘
    │                    │
    │                    ▼
    │             ┌──────────────┐
    │             │ Conversion   │
    │             │ Pipeline     │  ← lead → account → payment
    │             └──────┬───────┘
    │                    │
    │                    ▼
    │             ┌──────────────┐
    │             │   Billing    │  ← Stripe subscriptions
    │             └──────────────┘
    │
    └─── reads/writes data/trade_leads.jsonl
```

## 44 Trades

| # | Trade ID | Name | Best Platform | Avg Job Value | Conv Rate |
|---|----------|------|---------------|---------------|-----------|
| 1 | `plumbing` | Plumbing | google_maps | $450 | 12% |
| 2 | `hvac` | HVAC | homeadvisor | $1,200 | 10% |
| 3 | `electrical` | Electrical | google_maps | $600 | 11% |
| 4 | `roofing` | Roofing | homeadvisor | $3,500 | 8% |
| 5 | `landscaping` | Landscaping | nextdoor | $800 | 15% |
| 6 | `painting` | Painting | yelp | $1,500 | 13% |
| 7 | `general_contracting` | General Contracting | homeadvisor | $8,000 | 6% |
| 8 | `cleaning` | Cleaning | nextdoor | $250 | 18% |
| 9 | `pest_control` | Pest Control | google_maps | $350 | 14% |
| 10 | `moving` | Moving | google_maps | $900 | 10% |
| 11 | `concrete` | Concrete | homeadvisor | $2,200 | 9% |
| 12 | `masonry` | Masonry | homeadvisor | $2,800 | 8% |
| 13 | `siding` | Siding | homeadvisor | $4,500 | 7% |
| 14 | `framing` | Framing | homeadvisor | $3,500 | 7% |
| 15 | `glass_and_glazing` | Glass & Glazing | google_maps | $600 | 11% |
| 16 | `drywall` | Drywall & Insulation | homeadvisor | $1,200 | 10% |
| 17 | `flooring` | Flooring | houzz | $2,000 | 12% |
| 18 | `tile` | Tile & Terrazzo | houzz | $1,500 | 11% |
| 19 | `finish_carpentry` | Finish Carpentry | houzz | $1,800 | 10% |
| 20 | `kitchen_and_bath` | Kitchen & Bath Remodeling | houzz | $12,000 | 5% |
| 21 | `deck_and_fence` | Deck & Fence | nextdoor | $3,000 | 9% |
| 22 | `gutter` | Gutter Services | homeadvisor | $400 | 14% |
| 23 | `window_replacement` | Window Replacement | homeadvisor | $3,500 | 7% |
| 24 | `tree_service` | Tree Service | nextdoor | $700 | 13% |
| 25 | `pool_service` | Pool Service | nextdoor | $300 | 16% |
| 26 | `water_damage_restoration` | Water Damage Restoration | google_maps | $2,500 | 8% |
| 27 | `fire_damage_restoration` | Fire & Smoke Restoration | google_maps | $5,000 | 6% |
| 28 | `mold_removal` | Mold Inspection & Removal | homeadvisor | $1,800 | 9% |
| 29 | `solar_installation` | Solar Installation | google_maps | $15,000 | 4% |
| 30 | `water_treatment` | Water Treatment | homeadvisor | $1,200 | 10% |
| 31 | `septic` | Septic Services | google_maps | $600 | 12% |
| 32 | `well_drilling` | Well Drilling | google_maps | $4,000 | 7% |
| 33 | `chimney` | Chimney & Fireplace | google_maps | $350 | 13% |
| 34 | `driveway_paving` | Driveway Paving | homeadvisor | $2,500 | 8% |
| 35 | `carpet_cleaning` | Carpet Cleaning | nextdoor | $200 | 19% |
| 36 | `handyman` | Handyman Services | nextdoor | $250 | 20% |
| 37 | `locksmith` | Locksmith | google_maps | $200 | 22% |
| 38 | `security_system` | Security Systems | google_maps | $800 | 9% |
| 39 | `fire_protection` | Fire Protection | google_maps | $700 | 10% |
| 40 | `dumpster_rental` | Dumpster Rental & Junk Removal | google_maps | $350 | 15% |
| 41 | `demolition` | Demolition Services | homeadvisor | $3,000 | 7% |
| 42 | `appliance_repair` | Appliance Repair | google_maps | $200 | 18% |
| 43 | `garage_door` | Garage Door Services | google_maps | $400 | 14% |
| 44 | `pressure_washing` | Pressure Washing | nextdoor | $300 | 17% |

## Key Modules

| Module | Role |
|--------|------|
| `engine/trades/trades.py` | `TRADE_REGISTRY` — config for all 44 trades |
| `engine/trades/discovery.py` | `TradeLeadDiscovery` — search platforms for leads |
| `engine/trades/convert.py` | `ConversionPipeline` — lead → account → payment storage |
| `engine/trades/scoring.py` | `score_trade_lead` — LLM-based lead scoring |
| `engine/trades/platforms.py` | Platform-specific searchers (google_maps, homeadvisor, angi, yelp, facebook, nextdoor, instagram, houzz) |
| `engine/persistence.py` | `save_leads` / `load_leads` — flat JSONL persistence |
| `scripts/seed_trades.py` | Batch discovery runner for all 44 trades |
| `scripts/key_wizard.py` | Interactive API key setup |
