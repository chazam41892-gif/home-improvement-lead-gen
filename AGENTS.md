# Agent Guide — Lead Gen Pro / Leviathan Growth Portal

## What this repo is

Production-grade B2B lead generation platform. It is also the first module inside
the Leviathan Growth portal at `growth.leviathansi.xyz`.

- **Backend:** FastAPI (`main.py`) + SQLite (`data/lead_gen.db`)
- **Frontend:** Static HTML in `static/`, Tailwind via CDN
- **Search:** Exa + Perplexity
- **Enrichment:** Apollo + Exa + LLM
- **Billing:** Stripe Checkout + subscription gating
- **Messaging:** Twilio (SMS/calls) + SendGrid (email)
- **Ads:** Google Ads + Meta Marketing API campaign launch scaffolds
- **Memory:** HiveMind vault bridge (`engine/key_vault.py`)

## Where agents should work

AI agents extending lead generation capabilities should target the
`leadgen-agents` branch:

```bash
git fetch origin leadgen-agents
git checkout leadgen-agents
```

Do **not** commit directly to `master`. Open a PR from `leadgen-agents` when
ready.

## How to add a new trade

1. Open `engine/trades/trades.py`
2. Add a new entry to `TRADE_REGISTRY` with the same shape as existing trades:
   - `name`, `platforms`, `keywords`
   - `avg_job_value`, `lead_cpl_ceiling`, `conversion_rate`
   - `seasons`, `urgency_triggers`, `best_platform`
3. Add natural-language keywords to `engine/scout.py` `_parse_natural_query`
   `industry_keywords` if users will type the trade name.
4. Run `python -c "from engine.trades.trades import get_trade_config; print(get_trade_config('your_trade'))"`
5. Add a test in `tests/test_engine.py`.

## How to add a new discovery platform

1. Add an async searcher to `engine/trades/platforms.py`
   - Signature: `async def search_x(trade: str, location: str, max_results: int) -> list[TradeLead]`
2. Register it in `PLATFORM_SEARCHERS`
3. Add the platform slug to the trade's `platforms` list in `engine/trades/trades.py`
4. Prefer Exa `site:` queries for new directories.

## How to add a new enrichment provider

1. Create a provider in `engine/enrichment/<provider>_enricher.py`
   - Inherit from `EnrichmentProvider`
   - Implement `is_available()` and `enrich(...)`
2. Wire it into `engine/enrichment/orchestrator.py` `_init_providers()`
3. Add to `set_provider_enabled()` valid set.

## How to add a new Growth portal module

1. Register the module in `engine/growth_portal/modules.py`:
   ```python
   register_module(Module(
       id="your_module",
       name="Your Module",
       slug="your-module",
       description="...",
       min_plan="starter",
       route_path="/module/your-module",
   ))
   ```
2. Add a handler in `engine/growth_portal/portal.py` `module_landing()` for the
   new module ID.
3. Add pricing to the profile page if the module changes tier requirements.

## How to add a new ad platform integration

1. Add a provider class in `engine/ad_apis.py` that mirrors `GoogleAdsAPI` or
   `MetaMarketingAPI`.
2. Implement `is_configured`, credential gating, and a `create_campaign` method.
3. Register the provider in `AdPlatformManager.__init__` and wire it in
   `AdPlatformManager.launch()`.
4. Document required env vars in `scripts/validate_env.py` and `main.py`.
5. Add a test in `tests/test_integration_hooks.py`.

## How to use the embedded lead-capture widget

1. Serve `static/widgets/lead-capture.js` from any page.
2. Include script attributes: `data-business`, `data-industry`, `data-primary`,
   `data-source`, `data-api`.
3. Form submissions hit `/api/capture/lead` and auto-attach UTM parameters.
4. Add new `data-*` attributes by updating `static/widgets/lead-capture.js`.

## How to validate a deployment

1. Run `python scripts/validate_env.py [minimal|demo|production]`.
2. Required vars for production are listed in `scripts/validate_env.py`.
3. The `/health` endpoint reports which integrations are configured at runtime.

## How to deploy to production via Cloudflare Tunnel

1. Provision a host with Docker (local server, NAS, VM, or VPS).
2. Clone this repo and create `.env` with production secrets.
3. Run `bash deploy/cloudflare/scripts/setup-tunnel.sh` to create a tunnel for
   `growth.leviathansi.xyz` and get a `TUNNEL_TOKEN`.
4. Add `TUNNEL_TOKEN` to `.env`.
5. Run `cd deploy/cloudflare && docker compose up -d`.
6. Verify `https://growth.leviathansi.xyz/health` returns `{"status":"ok"}`.

## Critical rules

- **ADD-ONLY.** Never delete existing files without archiving to `_archive/YYYY-MM-DD/`.
- **Test before claiming done.** Run `python run_tests.py`.
- **Never hardcode secrets.** Use `engine.key_vault.KeyVault.get(service)`.
- **Use full Windows paths** when reporting files to HaChazal.
- **Update this file** if you change architecture or add extension points.

## Verification commands

```bash
python -c "import main; print('OK')"
python run_tests.py
python -m pytest tests/test_api.py tests/test_engine.py -q
```
