# LEAD GEN PRO — Bring Your Own Keys Lead Generation Module

**The complete, customizable lead generation engine. Bring your Exa API key, start finding leads in 30 seconds.**

```bash
pip install -r requirements.txt && python run.py
```

## What You Get

- **Exa-powered web search** — Real business discovery, not simulated data
- **Smart scoring** — Contact completeness, business presence, industry relevance, location match
- **Chat interface** — Type "Roofing contractors in Eugene, OR" and get qualified leads
- **Dashboard** — Beautiful dark-theme UI with real-time stats
- **BYOK** — Bring your own Exa API key. No subscriptions. No lock-in.
- **Export** — CSV and JSON exports with one click
- **Fully customizable** — Industry, location, scoring thresholds, all configurable

## Quick Start

1. Get a free Exa API key at [dashboard.exa.ai](https://dashboard.exa.ai) (1000 free searches/month)
2. Run `python run.py`
3. Open `http://localhost:8080`
4. Paste your Exa key in Settings
5. Type what you need — "Plumbers in Dallas, TX"

## API

The FastAPI backend at `/docs` gives you full programmatic access:
- `POST /api/search/natural` — Natural language lead search
- `POST /api/search` — Structured search with config
- `GET /api/leads` — Browse all leads
- `GET /api/export/csv` — CSV export
- `GET /api/stats` — Analytics

## BYO Keys

| Service | Required | Get Key |
|---------|----------|---------|
| Exa AI  | Yes      | https://dashboard.exa.ai |

## Customization

- Industry targeting (30+ industries)
- Location targeting (city, state, zip, radius)
- Scoring threshold (0-100)
- Result count (10-100)
- Domain include/exclude lists
- All settings available via UI or API

## Architecture

```
run.py → main.py (FastAPI) → engine/scout.py → engine/search/exa.py
                                    ↓
                            engine/utils/scoring.py
                                    ↓
                            JSON / CSV export
```
