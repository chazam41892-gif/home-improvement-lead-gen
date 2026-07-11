# Agent Guide — Lead Gen Pro / Leviathan Growth Portal

## What this repo is

Production-grade B2B lead generation platform. It is also the first module inside
the Leviathan Growth portal at `growth.leviathansi.xyz`.

- **Backend:** FastAPI (`main.py`) + SQLite (`data/lead_gen.db`)
- **Frontend:** Static HTML in `static/`, Tailwind via CDN
- **Search:** Exa + Perplexity
- **Enrichment:** Apollo + Exa + LLM
- **Billing:** Stripe Checkout + subscription gating
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
