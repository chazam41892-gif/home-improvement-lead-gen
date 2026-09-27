# DEEP CODE AUDIT — home-improvement-lead-gen

**Date:** 2026-09-27 · **Branch:** `leadgen-agents` · **HEAD:** `029fa62` · **Auditor:** Hermes (5 parallel subsystem auditors + independent re-verification)

**Project root:** `C:/Users/chaza/leviathan/home-improvement-lead-gen` (confirmed — holds `main.py`, `pyproject.toml`, `AGENTS.md`)
**Interpreter:** `py -3.14` (Python 3.14.7). The default `python` (3.11) lacks the project deps and cannot import `main`.

**Excluded from analysis:** `build/lib/**` (stale duplicate of `engine/` that has drifted), `dist/**`, `legacy/**`, `__pycache__/**`, `node_modules/**`, `leadgen_pro.egg-info/**`, `.lpls/**` (baseline snapshot).

---

## ⚠️ DISCLOSURE — this audit polluted the working database

`data/lead_gen.db` is **not** test-isolated. `tests/conftest.py` never redirects the DB path, so every test run writes to the real file. During this audit:

- The suite ran 5+ times, each inserting leads, nurture sequences, schedules, and campaigns.
- My own live probes wrote rows — measured revenue climbing **$2,619 → $2,813 → $2,819** during the session.
- One auditor's harness executed `DELETE FROM leads` while probing a cross-tenant clear, **destroying real lead rows**. `PRAGMA integrity_check` = ok, `freelist_count` = 0, no recoverable residue. Those rows are gone and were not reconstructed.

`data/lead_gen.db` is gitignored, so nothing left the machine. But **any numbers currently in that DB are test garbage** — `/api/trades/revenue` reporting "$2,619 revenue" is fake, from `Test Plumbing Co` accounts. Verify the DB's real provenance before trusting anything in it.

---

## VERDICT

| Dimension | Score | Basis |
|---|---:|---|
| **Code built** | ~85% | 5,725 LOC in `engine/`, 124 routes, all 7 of the prior audit's gaps have real code |
| **Code verified** | ~35% | 29/83 `/api` routes covered by any test |
| **Test-suite honesty** | 50% | 33 of 66 tests are real behavioral; 13 tautological; 19 smoke-only |
| **Production readiness** | ~15% | 0 of 13 external providers credentialed; every send/launch is non-functional |
| **Overall** | **~55–60%** | Capability is ahead of delivery |

**The build is genuinely good. The wiring is genuinely broken.** This is not a scaffold — every audited subsystem has exactly one production call site and zero test-only subsystems. The failure is a broken key registry, one SDK type mismatch, and a test suite that cannot see either.

---

# CRITICAL

### C-1 · Live secrets committed to git in the production deploy compose
`deploy/cloudflare/docker-compose.yml:12-14` is **tracked in git** and is **not** gitignored:
```
12:      - AUTH_DISABLED=1
13:      - API_KEY=<40-char value>
14:      - JWT_SECRET=<64-char value>
```
`git ls-files --error-unmatch` → tracked. `git check-ignore` → NOT IGNORED. Introduced by `8ffbe0d`.
`AUTH_DISABLED=1` on the same compose means `main.py:97-126` makes `verify_api_key()` return `True` for **every** caller through the public `growth.leviathansi.xyz` tunnel.
**Fix:** rotate both immediately → `git rm --cached` the file → replace with `${API_KEY:?required}` → drop `AUTH_DISABLED=1` → history-rewrite. Treat both as burned.

### C-2 · Every valid Stripe webhook returns HTTP 500 — no payment is ever recorded
`engine/stripe_integration.py:140` calls `.get()` on a `stripe.StripeObject`. Installed SDK is **15.2.0**, where `StripeObject` is no longer a `dict` subclass.
**Independently re-verified by me:**
```
  stripe SDK version: 15.2.0
  StripeObject dict subclass?: False   has .get?: False
  VALID signed webhook -> HTTP 500 {"error":"Internal server error"}
  ev.get('type') -> AttributeError CONFIRMED: get
```
Signature verification itself is **correct** (bad secret, tampered body, missing header, stale timestamp all rejected) — only the handler body is broken. Same bug at `:156`, `:193`, `:202`.
**Fix:** `event["type"]` / `event["data"]["object"]` (works on both SDKs), add a `_g()` helper, pin `stripe==15.2.0`, add a signed-webhook test (there is none — `tests/` never references `construct_event`).

### C-3 · Ad launcher fabricates a campaign id and the UI says "Campaign created!"
`main.py:795` mints `campaign_id = f"camp_{uuid4().hex[:12]}"` unconditionally; `engine/ad_apis.py:240` hard-codes `{"ok": True, **results}` over a failed sub-result. The provider honestly sets `simulated: True`, but it's **nested** under `google_ads`, so the top level has no `simulated` key. `static/index.html:2741` alerts `Campaign created!`.
**Independently re-verified by me:**
```
  HTTP 200 | top-level ok: True | campaign_id: camp_fff6e4a3bcd1
  top-level simulated: <ABSENT>
  google_ads: ok=True simulated=True note=Google Ads credentials not configured. Returning preview.
```
The row persists to `ad_campaigns` with `status='created'` and shows in the campaign list. **This is the one finding where the user reads a fabricated external side effect and acts on it.**
**Fix:** derive `ok` from sub-results; refuse to mint an id when the platform returned none (`HTTP 502`); branch the alert on `data[platform]?.simulated`.

### C-4 · No multi-tenant isolation on any business table
`org_id` is issued in every JWT and used for verticals, but is **absent from every table holding customer data.** Verified by me:
```
  leads                org_id present: False
  nurture_sequences    org_id present: False
  schedules            org_id present: False
  ad_campaigns         org_id present: False
  trade_accounts       org_id present: False
  appointments         org_id present: False
```
`/api/leads/{id}`, `PATCH`, `DELETE` and `DELETE /api/leads` call `verify_api_key` then ignore the caller. `scout.py:439` is a bare `DELETE FROM leads`. Any authenticated tenant can read and **wipe every other tenant's leads**.
**Fix:** add `org_id TEXT NOT NULL` to all six tables and scope every query. **Do not run this multi-tenant until done — run single-tenant.**

### C-5 · Tests write to the production database
`tests/conftest.py` sets env keys but never redirects the DB path; `engine/database.py:9` reads `DATABASE_FILE`, but `engine/trades/convert.py:21-23` **overrides it at import** via `Database.set_db_file()`, and `main.py:218` constructs `ConversionPipeline()` at module scope. The env var is silently discarded process-wide.
Consequence: the suite is green while inserting `Test Plumbing Co` accounts, `Unit Test Campaign` rows, and `api-test@example.com` nurture sequences into the working DB.
**Fix:** make the test DB path actually authoritative; assert isolation in a test.

### C-6 · App cannot boot without manually exported env vars
`main.py:42` imports `engine.auth` **before** `load_dotenv()` executes at `main.py:47`. `engine/auth.py:25-31` reads `os.environ["JWT_SECRET"]` at import time.
```
$ py -3.14 -m uvicorn main:app
RuntimeError: JWT_SECRET is required for production auth   (exit 1)
```
`.env` line 10 **has** `JWT_SECRET` — it is simply loaded too late. `AGENTS.md`'s own first verification command (`import main`) fails on a clean checkout for this reason.
**Fix:** move `load_dotenv()` above the `engine.*` imports.

---

# HIGH

### H-1 · The Docker image cannot boot
`requirements.txt` has **zero** entries for `beautifulsoup4`, `lxml`, `playwright`, or `pytest` (grep count = 0), but `main.py:23` → `engine/scout.py:16` → `engine/search/browser_agent.py:11` imports them unconditionally. `CMD ["python","main.py"]` dies with `ModuleNotFoundError: No module named 'bs4'`. CI's `python run_tests.py` also cannot pass (no pytest).
**Fix:** add the four deps; make `browser_agent` import lazy so an optional provider degrades instead of killing the app.

### H-2 · The published wheel is unusable
`pyproject.toml` has no `py-modules` (grep = 0), so `main.py`, `run.py`, `enrichment.py`, `scoring_llm.py` are never installed — yet `entry_points.txt` ships `leadgen = run:main`.
```
  FAIL leadgen_pro -> ModuleNotFoundError
  FAIL main        -> ModuleNotFoundError
  FAIL run         -> ModuleNotFoundError
  OK   engine      -> ...site-packages\engine\__init__.py
```
`MANIFEST.in` covers the sdist but has no effect on the wheel.
**Fix:** `[tool.setuptools] py-modules = ["main","run","smoke_test","enrichment","scoring_llm"]` + a CI wheel-install gate.

### H-3 · Twilio, SendGrid, Google Ads and Meta keys cannot be registered by any means
The call sites request `twilio_sid`, `sendgrid`, `google_ads_dev_token`, `meta_access_token`… but `engine/key_vault.py:59-82` `SERVICE_KEYS` declares 22 names and **none of those are among them**. The only registration API rejects them:
```
  stripe_secret            -> HTTP 200 ACCEPTED
  twilio_sid               -> HTTP 400 {'error': 'Unknown service: twilio_sid'}
  sendgrid                 -> HTTP 400 {'error': 'Unknown service: sendgrid'}
  google_ads_dev_token     -> HTTP 400 {'error': 'Unknown service: google_ads_dev_token'}
  meta_access_token        -> HTTP 400 {'error': 'Unknown service: meta_access_token'}
```
Compounded by `key_vault.py:125` — on HiveMind success `load()` **returns early**, skipping the `os.environ` loop, so even `.env` keys are ignored. **No SMS or email can ever be sent, in any configuration.**
**Fix:** add ~17 `SERVICE_KEYS` entries using the names the call sites already use; merge the env layer instead of early-returning.

### H-4 · A STOP reply never suppresses anything (TCPA / CAN-SPAM)
`nurture.py:766-784` `handle_incoming_reply` writes `leads.sms_consent = 0` — **not** the `opt_outs` table the dispatcher actually reads at `nurture.py:353`. `record_stop()`, the only writer of `opt_outs`, has **zero production call sites**. The suppression logic itself is correct and proven to work — it is simply unreachable. Additionally, opt-out is per-channel, so an SMS STOP does not stop email.
**Fix:** route inbound STOP into `_record_opt_out` for all channels; expose `POST /api/nurture/opt-out`.

### H-5 · A failed payment leaves the account active
`stripe_integration.py:201-207` `_on_invoice_failed` is `logger.warning` and nothing else. Executed: `status before='active' after invoice.payment_failed='active'`. No `past_due`, no suspension — a bouncing card keeps full access for weeks.
**Fix:** a shared `_apply_subscription_state()` writer + a `customer.subscription.updated` handler + a dunning sweep.

### H-6 · CORS is wildcard **with** credentials
`.env` sets `CORS_ORIGINS=*`; `main.py:276-282` combines it with `allow_credentials=True`. Starlette then reflects any origin. Verified by me:
```
  Origin: https://evil.example -> 200  ACAO=https://evil.example  ACAC=true
  Origin: null                 -> 200  ACAO=null                 ACAC=true
```
Any website can read authenticated API responses from a logged-in operator's browser.
**Fix:** never `*` with credentials; default to a localhost list.

### H-7 · 66 of 125 routes have neither auth nor rate limiting
Includes all CRM-plus, growth-portal and tracking routes. Unauthenticated reads of live data confirmed: `/api/trades/accounts` (full customer list), `/api/trades/payments`, `/api/trades/revenue`, `/api/nurture/sequences` (names, emails, phones), plus unauthenticated `PUT /api/routing/config`. `/docs`, `/redoc`, `/openapi.json` publish the full schema anonymously.
**Fix:** router-level `dependencies=[...]` so new routes are protected by default; disable docs in production.

### H-8 · `AUTH_DISABLED=1` disables auth globally and silently
`main.py:97-126` — one env var makes every `verify_api_key()` return `True` for any caller. Your `.env` sets it. With it, `engine/auth.py:30` substitutes a random per-process JWT key, so **tokens silently stop validating after every restart**.
**Fix:** refuse to start when `AUTH_DISABLED` is truthy and the bind address is non-loopback.

### H-9 · Perplexity fabricates a lead and reports `ok: true`
`engine/search/perplexity.py:90-100` — when a response has no `citations`, prose is converted into `SearchHit`s with `url=""` and hardcoded `score=1.0`, which flow into `engine._leads` indistinguishable from a real lead.
```
  title : 'roofers in Austin TX'   url: ''   score: 1.0
  engine.search() -> {"ok": true, "count": 1, "leads":[{... "url":"", "score":36.0}]}
```
**Fix:** never synthesize hits from a prose answer; return `error=` or expose the prose as a separate `answer` field with `count: 0`.

### H-10 · All 13 platform searchers discard `SearchResult.error`
`engine/trades/platforms.py` — not one of the 13 reads `result.error`. A 401, a rate limit, and a genuinely empty result set are indistinguishable; `discover()` caches the empty list as a successful scan. Verified by introspection across all 13 functions.
Compounding: `KeyVault.get("exa")` returns an **8-character** placeholder (a vault entry literally labelled `'test'`), so Exa is live-but-401 while reporting itself healthy.
**Fix:** check `result.error` in every searcher; add a length/plausibility guard to `KeyVault.get`; purge the 8-char entry; make `.env` take precedence over the vault.

### H-11 · `search_google_maps` never contacts Google Maps
`engine/trades/platforms.py:26-52` runs four generic web queries and labels every hit `source="google_maps"` — false provenance, on the `best_platform` of 20+ trades. Only 1 of 13 platforms has a real platform-specific integration; the other 12 are Exa web-query wrappers.
**Fix:** implement a real Places API provider, or rename to `web_search` and correct every `best_platform` label.

### H-12 · `crm_tools.py` is in-memory only and its `db_path` is never used
`crm_plus/crm_tools.py:22-27` accepts `db_path`, stores it, never touches it. Executed: instance A saw 2 leads, "restart" instance B saw 0. IDs are positional (`f"LEAD-{len(self.leads)+1:05d}"`) so they **collide after any deletion**. Nothing imports the file.
**Note:** the prior report's claim that `crm_plus_routes.py` returns hardcoded zeros is **retracted** — it is genuinely SQLite-backed and verified persistent (a written lead survived an engine-state clear). Only `/api/crm/stats` and `/api/crm/history` still reset to zero on restart (`crm_push._history` is a list).

### H-13 · `/api/chat/collaborate` returns `ok: true` whether an LLM answered or a static string did
`main.py:995-1023` (uncommitted work) falls back to 5 hardcoded strings on missing key *or any exception*, logging only a warning. The client cannot tell.
**Fix:** return a `degraded: true` flag.

### H-14 · `scout.py:266-267` computes the LLM score then discards it
`if routed_lead.get("llm_score"): pass` — `LeadResult` has no `llm_score` field, so the qualification signal is never stored, returned, or persisted.

---

# MEDIUM

| # | Finding | Location |
|---|---|---|
| M-1 | `data/.vault_key` **tracked in git** (commit `299dc10`) despite `*.key` + `data/` ignore rules — gitignore never applies retroactively. Mitigating: current `key_vault.py` no longer reads it, so it's a dead 44-byte artifact, but it is in history. | `git ls-files` |
| M-2 | Two endpoints **500 on every call**: `user.get("sub")` on a `None` user when auth is disabled | `main.py:1100`, `main.py:1136` |
| M-3 | Rate limiter keys on the raw `Authorization` header → rotating token = fresh bucket per request; `_buckets` has no TTL or eviction | `main.py:149-153` |
| M-4 | Static API key compared with `==`, not `hmac.compare_digest` | `main.py:114` |
| M-5 | Startup log at `main.py:106` says "API routes will reject requests until a key is configured" — **false**; JWT and `lgn_` keys work with no `API_KEY` | `main.py:106` |
| M-6 | `/api/capture/lead` is unauthenticated, unthrottled, no CAPTCHA, no field-length cap — 50 consecutive writes all returned 200 | `main.py:630` |
| M-7 | JWT lives 7 days with no refresh, no revocation list, no logout that invalidates an issued token | `engine/auth.py:23` |
| M-8 | Smart routing aborts the enrichment chain on a self-reported `0.3` confidence that a **zero-field** browser crawl can reach, so the provider that would have data is never called | `orchestrator.py:196-200` |
| M-9 | `update_lead()` silently discards 12 of its 20 whitelisted fields (`hasattr` is False for non-dataclass keys) yet still returns success | `scout.py:405-413` |
| M-10 | Every captured lead is hardcoded to `_SimpleScore(50.0)` across all 5 sub-scores | `capture.py:147` |
| M-11 | `_resolve_industry` returns the literal `"home improvement"` on **every** branch — no trade classification | `capture.py:206-215` |
| M-12 | Three frontend→backend contract bugs: `POST /api/settings/reset` **does not exist** (404, yet the UI alerts "Settings reset"); `GET /api/billing/subscription/demo_account` sends a literal id; `fetch('/deploy/deploy.sh')` 404s and the catch-block substitutes a *different* script | `index.html:3070`, `:2084`, `app.html:755` |
| M-13 | `leadgen-workflows/src/index.ts` is Cloudflare's **hello-world template, verbatim** — fake file list, `Math.random()` coin-flip failure, fetches Cloudflare's public IP API. Zero relation to lead gen. | `index.ts:31-79` |
| M-14 | `crm_support.py` cannot be imported (`from ..base` escapes above top-level); `crm_sales.py` imports `leviathantalon_catalog`, which is in no requirements file and only resolved from a sibling checkout on this box | `crm_support.py:2`, `crm_sales.py:4` |
| M-15 | `CrmPlusCommandCenter.kt` is copy-paste from another project — every class it imports is absent, `serverUrl` is a hardcoded LAN IP on the wrong port, and its status line reads "7 Agents Active" with `result` assigned and never used | `CrmPlusCommandCenter.kt:176-196, 238` |
| M-16 | `POST /api/crm/outreach_swarm` returns `agents_active: 7` from `len()` of a hardcoded literal list — always 7, nothing dispatched | `crm_plus_routes.py:83-92` |
| M-17 | `/health` mixes two sources of truth: `*_configured` flags read the **vault**, `missing_config` reads **`os.getenv`**. `ad_apis._missing_env` is named for env but queries the vault, telling operators to set env vars that are never read. | `main.py:70-89, 306-307`, `ad_apis.py:228-230` |
| M-18 | `simulator.py` emits dev-quality random projections with **no `simulated` flag** in the payload, so an estimate is indistinguishable from a measurement | `simulator.py:41-49` |
| M-19 | `ads.py:490` `hash(headline) % len(variants)` — Python string hashing is randomized per process, so ad copy variants change on every restart | `ads.py:490` |
| M-20 | `electron-shell/main.js:72` calls `dialog.showInputBoxSync`, which does not exist in Electron — the server-URL text box never appears | `main.js:72` |
| M-21 | `scripts/pre-commit-check.sh` only greps for a file named exactly `.env`; executed against the known-bad compose it returns exit 0. It would never have caught C-1. | `pre-commit-check.sh` |

---

# LOW / HYGIENE

- **Version drift in four places:** `pyproject.toml:7` = `3.1.3`, `main.py:271` = `3.1.0`, `main.py:297` = `3.2.0`, `main.py:1523` = `v3.1.0`. `/health` reports a version the app does not have.
- `.env` contains **`JWT_SECRET` twice** (lines 10 and 12); `load_dotenv` binds the first.
- `data/lead_gen.db` is opened **twice** at startup with two different path spellings (`data/lead_gen.db` and `data\lead_gen.db`).
- `auth.py:100-108` bare `except: pass` around the `google_id` migration silently skips index creation on any failure.
- `stripe_integration.py:15` `_MAPPINGS_FILE` has zero references.
- `enrichment.py` (root, 3.3 KB) and `engine/enrichment/orchestrator.py` both export `enrich_lead` with **incompatible signatures** — `(lead: dict)` vs `(business_name, trade, ...)`. Only the root one is registered (`main.py:186`); the engine one is unreachable and calling it raises `TypeError`.
- `trades/base.py:63-69` `TradeLeadSource.discover()` raises `NotImplementedError` with zero subclasses and zero callers.
- `SearchConfig.include_domains` / `exclude_domains` are declared and defaulted but **never passed** to any provider — all domain filters are dead.
- `TradeLead.rating` / `review_count` are never populated, and dedup at `discovery.py:54-57` makes `platforms_found` always exactly 1 — so the `+5`/`+2`/`+10` scoring bands at `scoring.py:29-42` are unreachable.
- `build/lib/engine/**` is a stale, drifted copy of `engine/**` shipped inside the sdist. Auditing it produces wrong conclusions; it should be deleted.
- `deploy/cloudflare/.env` and `.env.bak` are untracked and correctly ignored — those are clean. The leak is the compose file.

---

# DOC INTEGRITY — the docs are actively misleading

| Claim | Verdict |
|---|---|
| `LEAD_GEN_ECOSYSTEM_STATUS.md:4` "✅ COMPLETE" / `:359` "PRODUCTION READY" | **FALSE — wrong project.** Describes `C:/Users/chaza/malika-memory/lead_generation_ecosystem`. All 8 component files it certifies are **absent** from this repo. |
| `pyproject.toml:8`, `README.md:5,20-21`, `DATA_FLOW.md:33,55,108` "44 trades, 8 platforms" | **FALSE.** Actual: **45 trades, 13 platforms.** Docs are stale-low. |
| `SECURITY_PROTOCOL.md:82` "All tests passing (53/54)" | **STALE** — now 65 passed / 1 skipped. |
| `SECURITY_PROTOCOL.md:76` "Rotate all 16 exposed keys — IN PROGRESS" | **STILL OPEN** — 16 keys still marked MUST ROTATE. |
| `README.md:178` "Built for production" | **STALE** — 54/83 routes untested; app won't boot. |
| `AUDIT_REPORT.md:217` "~12% complete" | **SUPERSEDED** — 4 of 7 gaps fixed, 3 partial, 0 regressed. |
| `AGENTS.md` "update this file if you change architecture" | **NOT HONORED.** Zero mentions of `engine/messaging/`, `engine/simulator.py`, `engine/search/browser_agent.py`, `crm_plus/`, `nurture.py`, `capture.py` — including the two subsystems that closed its own #1 and #7 gaps. |
| `AGENTS.md` verification command 1 (`import main`) | **FAILS** on a clean checkout (C-6). Commands 2–4 pass. |

**GAP status from `AUDIT_REPORT.md`, re-derived from the current tree:** GAP-1 landing page **FIXED** · GAP-2 advertising **PARTIAL** (routes + copy real, launch simulated) · GAP-3 conversion tracking **PARTIAL** (pixel live, no attribution layer) · GAP-4 immediate follow-up **FIXED** · GAP-5 business fundamentals **FIXED** · GAP-6 simulated data **IMPROVED, NOT GONE** · GAP-7 LP form→CRM **FIXED** (but no dedup, no CRM upsert, hardcoded industry).

---

# TEST SUITE HONESTY

`65 passed, 1 skipped` — reproduced across **5 orderings**, 5 isolated files, and 4 single-test runs. **No order-dependence, no flakiness.** The suite is deterministic; it is just not very meaningful.

| Class | Count | % |
|---|---:|---:|
| Real behavioral | **33** | 50% |
| Tautological / self-fulfilling | **13** | 20% |
| Smoke / shape-only (status code or key presence) | **19** | 29% |
| Skipped | 1 | 1.5% |

**`/api` route coverage: 29/83 = 35%.** All 5 billing routes, all landing routes, `/api/capture/lead`, `/api/auth/login`, `/api/trades/discover-all` are untested.

Provably unfailable assertions:
```python
# tests/test_integration_hooks.py:50-51 — always True, cannot fail
assert status["google_ads"]["configured"] is False or True
# tests/test_growth_portal.py:89 and test_crm_plus.py:96 — passes either way
assert resp.status_code in (200, 401)
# tests/test_growth_portal.py:228-252 — reimplements the product inside the test
provider = BrowserSearchProvider()   # created, NEVER used
```
Plus: `test_engine.py:11-24` accepts any score in a 50-point window (real value 85.0); `test_engine.py:29` / `test_api.py:5` count **dict entries**, not reachable trades.

**Nothing in the suite would have caught C-1, C-2, C-3, C-5, C-6, H-1, or H-2.**

---

# WHAT IS GENUINELY GOOD — protect this

- **Stripe signature verification is correct.** All four attack classes rejected. Use the official `construct_event` with the tolerance check intact.
- **Webhook idempotency is sound by construction** — `account_id TEXT PRIMARY KEY` + `INSERT OR REPLACE` means a redelivered event cannot double-grant.
- **Landing pages emit real, servable, submittable HTML**, correctly wired to `/api/capture/lead`, escaped, with colour/URL validation, persisted to sqlite.
- **Scheduler and nurture loop are both started** in the lifespan — not test-only.
- **Outbound provider HTTP bodies are correct** (Twilio `Messages.json`, SendGrid `/mail/send`, Google Ads OAuth + `campaigns:mutate`, Meta graph POST) and **fail closed** with `ok:false` + `simulated:true` — exactly the pattern the ad launcher should copy.
- **No SQL injection.** An AST sweep of all 102 `execute*` call sites found 99 constant strings and 3 f-strings; all 3 interpolate a hardcoded allow-list of column names, never caller data. Verified with a hostile-input probe.
- **Android (30 Retrofit endpoints, 14 screens) is fully real** — 0 contract mismatches, 0 sample data, proper `contextIsolation`/no-`nodeIntegration` in Electron.
- **The composition root is exemplary** — every subsystem has exactly one production call site; nothing is test-only or orphaned.
- `deploy.yml` fails safe when deploy secrets are absent; CI runs real gitleaks + trufflehog + tests.

---

# ROADMAP

**P0 — rotate and contain (today)**
1. Rotate `API_KEY` + `JWT_SECRET` from `deploy/cloudflare/docker-compose.yml`; `git rm --cached`; strip `AUTH_DISABLED=1`; history-rewrite. (C-1)
2. `git rm --cached data/.vault_key`. (M-1)
3. Stop the fabricated campaign id + alert. (C-3)
4. Add the 4 missing deps; make `browser_agent` import lazy; verify the image boots. (H-1)

**P1 — unblock the money path**
5. Fix the Stripe handler (`event["type"]`, `_g()` helper, pin SDK) + add a signed-webhook test. (C-2)
6. Add the ~17 `SERVICE_KEYS` entries; merge env+vault layers. (H-3)
7. Route inbound STOP into `opt_outs`. (H-4)
8. Add `py-modules`; add a wheel-install gate to CI. (H-2)
9. Move `load_dotenv()` above the engine imports. (C-6)

**P2 — correctness & safety**
10. Add `org_id` to the six business tables **or** declare the app single-tenant in code. (C-4)
11. Make the test DB authoritative; assert isolation. (C-5)
12. Delete `build/lib/**`; fix the four version strings; fix the `enrich_lead` collision; delete `leadgen-workflows/` and `CrmPlusCommandCenter.kt`.

**P3 — production readiness (needs vendor accounts, not code)**
13. Credential Exa/Perplexity/Apollo; purge the 8-char `exa` vault entry first.
14. Credential Google Ads / Meta / Twilio / SendGrid after H-3.
15. Fix the 3 contract bugs (M-12); real scoring and industry resolution (M-10, M-11).
16. Raise `/api` test coverage from 35%; delete the 13 tautologies.
17. Rewrite or delete `LEAD_GEN_ECOSYSTEM_STATUS.md`; correct 44/8 → 45/13 everywhere; bring AGENTS.md up to date.
