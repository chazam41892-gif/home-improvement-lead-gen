# BASELINE — home-improvement-lead-gen

**Snapshotted:** 2026-07-04
**Version:** Pre-patch state
**Snapshot location:** `.lpls/baseline/snapshot-v1/`

## Working state at freeze
- FastAPI server starts on port 8080
- 15+ endpoints defined in main.py
- Engine modules: search (Exa, Perplexity), scoring, export, router, scout, scheduler
- Tier 3: merger, scheduler
- Tier 4: landing page generator, capture processor, thank-you page
- Tracks: ads, nurture, business config, CRM push
- Android app in `android/`
- Tauri desktop app in `desktop/`
- Dockerfile for production

## Known issues documented in audit
`engine/crm_push.py` reports false success
`engine/search/perplexity.py` wrong endpoint
`engine/capture.py` silent error swallowing
`main.py` CORS misconfig + race conditions
`enrichment.py` stale env vars
See full audit for 27 bugs across CRITICAL/HIGH/MEDIUM

## Git
Remote: `origin https://github.com/metanoiaunlimited418-coder/Codenoia.git`
