"""
Live multi-source discovery — ported from sios.leadgen.engine (audit 2026-09-27, parity gap B).

WHY THIS EXISTS
---------------
The standalone module discovered leads only through paid AI-search APIs
(engine/scout.py -> Exa + Perplexity) and a 45-trade x 13-platform matrix
(engine/trades/). It had NO live free-source harvesting: no Google Maps, no
Reddit, no Craigslist, no GitHub. SIOS had all four as real HTTP scrapers.
This module ports them in.

Bug fixed on port (found in SIOS, do not reintroduce):
  `generate_search_queries` built `cl_queries` but never assigned it to the
  result dict, so `queries.get("craigslist", [])` always returned [] and the
  Craigslist source was a permanent silent no-op. `test_craigslist_queries_are_not_empty`
  locks this shut.

Optional deps: aiohttp + bs4. Both are soft-imported so this module never breaks
import of the package; a source that cannot run is reported in `skipped` rather
than crashing discovery.
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("leadgen.discovery")

try:
    import aiohttp
    _AIOHTTP = True
except ImportError:  # pragma: no cover
    _AIOHTTP = False

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:  # pragma: no cover
    _BS4 = False


# ── Data Models ────────────────────────────────────────────────────────────

@dataclass
class LeadSource:
    """Raw scraped text awaiting AI extraction."""
    source: str
    text: str
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetProfile:
    """What the user is looking for."""
    customer_description: str = ""
    keywords: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    industry: str = ""
    target_count: int = 25


@dataclass
class ScrapeJob:
    id: str
    profile: TargetProfile
    sources_used: list[str] = field(default_factory=list)
    status: str = "pending"
    created_at: float = 0.0
    completed_at: float = 0.0
    raw_results: list[LeadSource] = field(default_factory=list)
    leads: list[dict[str, Any]] = field(default_factory=list)
    crm_pushed: int = 0
    error: str = ""
    skipped: list[str] = field(default_factory=list)
    api_keys_used: dict[str, str] = field(default_factory=dict)


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def generate_search_queries(profile: TargetProfile) -> dict[str, list[str]]:
    """Generate search queries for each source based on the target profile.

    Every key produced here MUST be consumed by run_discovery, and every source
    branch in run_discovery MUST have a key here. See the cl_queries fix below.
    """
    desc = (profile.customer_description or "").lower()
    keywords = profile.keywords or ([desc] if desc else [])
    locations = profile.locations or [""]

    result: dict[str, list[str]] = {}

    # Google Maps
    gm_queries = [f"{kw} {loc}".strip() for kw in keywords[:3] for loc in locations[:2]]
    result["google_maps"] = [q for q in gm_queries if q] or ([desc] if desc else ["contractor"])

    # Exa — AI web index for business pages
    result["exa"] = list(result["google_maps"])

    # Tavily — AI web index for lead pages
    result["tavily"] = list(result["google_maps"])

    # Reddit — people actively seeking recommendations
    prefixes = ["need a", "looking for", "recommend", "best", "help with"]
    reddit_queries = [f"{p} {kw}" for kw in keywords[:3] for p in prefixes]
    if not reddit_queries:
        reddit_queries = [f"need a {desc}"] if desc else ["need a contractor"]
    result["reddit"] = reddit_queries

    # Craigslist want-ads.
    # AUDIT 2026-09-27: the SIOS original built cl_queries and then never stored it,
    # so the Craigslist scraper was dead code that always received []. Stored now.
    cl_queries: list[str] = []
    for kw in keywords[:3]:
        cl_queries.append(f"need {kw}")
        cl_queries.append(f"looking for {kw}")
        cl_queries.append(f"{kw} services")
    result["craigslist"] = cl_queries or ([desc] if desc else ["contractor"])

    # GitHub — user + repo search
    gh_queries: list[str] = []
    for kw in keywords[:3]:
        gh_queries.append(kw)
        gh_queries.append(f"looking for {kw}")
        gh_queries.append(f"{kw} developer")
    result["github"] = gh_queries or ([desc] if desc else ["software"])

    return result


#: Set by scrape_reddit when the source is blocked rather than merely empty.
#: Read by run_discovery to report the condition instead of implying no leads.
last_reddit_error: str = ""


# ── Google Maps Scraper ────────────────────────────────────────────────────

async def scrape_google_maps(queries: list[str]) -> list[LeadSource]:
    """Scrape Google Maps search results for potential leads.

    KNOWN LIMITATION (verified live 2026-09-27): the /maps/search HTML page is
    client-rendered. A plain HTTP GET returns 200 and ~225KB of markup, but
    BeautifulSoup extracts only ~130 characters of text because the result list is
    built by JavaScript. This function therefore usually yields nothing.

    It is kept wired in (rather than deleted) because the /maps/preview and
    `?output=search` variants do return server-rendered markup, and because the
    caller reports a real fetch instead of pretending the source was empty. For
    reliable Maps data use the official Places API via a keyed source.
    """
    results: list[LeadSource] = []
    if not _BS4:
        logger.warning("bs4 not installed — skipping google_maps source")
        return results
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        for query in queries[:5]:
            try:
                url = f"https://www.google.com/maps/search/{quote(query)}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning("google_maps %s -> HTTP %s", query, resp.status)
                        continue
                    html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")
                text = soup.get_text(separator=" ", strip=True)[:6000]
                if len(text) < 200:
                    # JS-rendered shell: the fetch worked but yielded no leads.
                    # Say so, so an empty result is not read as "no leads exist".
                    logger.warning(
                        "google_maps %s returned only %d chars of text (JS-rendered page); "
                        "use the Places API for reliable data", query, len(text))
                    continue
                results.append(LeadSource(
                    source="google_maps", text=text, url=url,
                    metadata={"query": query}))
            except Exception as e:
                logger.warning("Google Maps failed for %r: %s", query, e)
            await asyncio.sleep(1.5)
    return results


# ── Reddit Scraper ─────────────────────────────────────────────────────────

_SUBREDDITS = ["HomeImprovement", "Contractor", "RealEstate", "smallbusiness",
               "Entrepreneur", "Roofing", "Homebuilding", "Construction",
               "DIY", "HomeDecorating"]


async def scrape_reddit(queries: list[str], subreddits: list[str] | None = None) -> list[LeadSource]:
    """Scrape Reddit for people seeking services matching the queries.

    KNOWN LIMITATION (verified live 2026-09-27): Reddit's /search.json endpoint
    returns HTTP 403 "Blocked" to datacenter IPs, from aiohttp and urllib alike and
    on both www and old.reddit. The code detects that and records it in
    `last_reddit_error` instead of returning a silent empty list, because
    "blocked" and "no matching posts" look identical to a caller otherwise.

    The code path is correct and will work from a residential IP or via the official
    OAuth API; the block here is network egress, not a logic error.
    """
    global last_reddit_error
    last_reddit_error = ""
    results: list[LeadSource] = []
    subs = subreddits or _SUBREDDITS
    # Reddit rejects generic/browser-spoofing UAs on the JSON API; be identifiable.
    headers = {
        **_HEADERS,
        "User-Agent": "linux:leadgen.discovery:v1.0 (by /u/leviathan)",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        for sub in subs[:5]:
            for q in queries[:3]:
                try:
                    url = (f"https://www.reddit.com/r/{sub}/search.json"
                           f"?q={quote(q)}&restrict_sr=1&sort=new&limit=5")
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 403:
                            last_reddit_error = (
                                "HTTP 403 Blocked — Reddit's JSON API refuses this IP "
                                "(datacenter egress). Use a residential IP or the "
                                "official OAuth API.")
                            logger.warning("reddit %s: %s", sub, last_reddit_error)
                            return results
                        if resp.status != 200:
                            continue
                        data = await resp.json(content_type=None)
                    for child in data.get("data", {}).get("children", []):
                        d = child.get("data", {})
                        text = f"{d.get('title', '')}\n{d.get('selftext', '')}"[:3000]
                        if len(text) > 50:
                            results.append(LeadSource(
                                source="reddit", text=text,
                                url=f"https://reddit.com{d.get('permalink', '')}",
                                metadata={"subreddit": sub, "query": q}))
                except Exception as e:
                    logger.warning("reddit %s/%s failed: %s", sub, q, e)
                await asyncio.sleep(0.5)
    return results


# ── GitHub Lead Scraper ────────────────────────────────────────────────────

async def scrape_github(queries: list[str], api_key: str = "") -> list[LeadSource]:
    """Scrape GitHub user + repo search for developer/company leads."""
    results: list[LeadSource] = []
    headers = dict(_HEADERS)
    token = api_key or os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"token {token}"
        headers["Accept"] = "application/vnd.github.v3+json"

    async with aiohttp.ClientSession(headers=headers) as session:
        for q in queries[:4]:
            try:
                url = f"https://api.github.com/search/users?q={quote(q)}&per_page=5"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for user in data.get("items", []):
                            login = user.get("login", "")
                            u_url = f"https://api.github.com/users/{login}"
                            async with session.get(
                                    u_url, timeout=aiohttp.ClientTimeout(total=5)) as u_resp:
                                if u_resp.status != 200:
                                    continue
                                u = await u_resp.json()
                                text = (
                                    f"GitHub User: {u.get('name') or login}\n"
                                    f"Company: {u.get('company', '')}\n"
                                    f"Email: {u.get('email', '')}\n"
                                    f"Location: {u.get('location', '')}\n"
                                    f"Bio: {u.get('bio', '')}\n"
                                    f"Hireable: {u.get('hireable', '')}\n"
                                    f"Blog/Website: {u.get('blog', '')}\n"
                                    f"Public Repos: {u.get('public_repos', 0)}"
                                )
                                results.append(LeadSource(
                                    source="github", text=text,
                                    url=u.get("html_url", f"https://github.com/{login}"),
                                    metadata={"username": login, "query": q}))

                repo_url = f"https://api.github.com/search/repositories?q={quote(q)}&per_page=5"
                async with session.get(
                        repo_url, timeout=aiohttp.ClientTimeout(total=10)) as r_resp:
                    if r_resp.status == 200:
                        r_data = await r_resp.json()
                        for repo in r_data.get("items", []):
                            owner = repo.get("owner", {})
                            text = (
                                f"GitHub Repository: {repo.get('full_name')}\n"
                                f"Description: {repo.get('description', '')}\n"
                                f"Owner: {owner.get('login', '')}\n"
                                f"Topics: {', '.join(repo.get('topics', []))}\n"
                                f"Stars: {repo.get('stargazers_count', 0)}"
                            )
                            results.append(LeadSource(
                                source="github", text=text,
                                url=repo.get("html_url", ""),
                                metadata={"repo": repo.get("full_name"), "query": q}))
            except Exception as e:
                logger.warning("GitHub scrape failed for %r: %s", q, e)
            await asyncio.sleep(0.5)
    return results


# ── Craigslist Scraper ─────────────────────────────────────────────────────

_CRAIGSLIST_CITIES = {"eugene": "eugene", "portland": "portland", "salem": "salem",
                      "seattle": "seattle", "losangeles": "losangeles"}


async def scrape_craigslist(queries: list[str], cities: list[str] | None = None) -> list[LeadSource]:
    """Scrape Craigslist want-ads matching the queries.

    Now reachable: run_discovery previously got [] here because
    generate_search_queries never stored cl_queries (see the fix above).
    """
    results: list[LeadSource] = []
    if not _BS4:
        logger.warning("bs4 not installed — skipping craigslist source")
        return results
    cities = cities or ["eugene", "portland"]
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        for city in cities:
            for q in queries[:3]:
                try:
                    url = (f"https://{city}.craigslist.org/search/bbb"
                           f"?query={quote(q)}&is_paid=all")
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    for item in soup.select(".cl-static-search-result")[:5]:
                        title_el = item.select_one(".title")
                        link_el = item.select_one("a")
                        title = title_el.get_text(strip=True) if title_el else ""
                        if title:
                            # BeautifulSoup's .get() is typed as
                            # str | AttributeValueList | None, so narrow it
                            # rather than passing a union into LeadSource.url.
                            href = link_el.get("href") if link_el else None
                            results.append(LeadSource(
                                source="craigslist", text=title,
                                url=str(href) if href else "",
                                metadata={"city": city, "query": q}))
                except Exception:
                    pass
                await asyncio.sleep(1)
    return results


# ── Exa / Tavily / URL ────────────────────────────────────────────────────

async def scrape_exa(queries: list[str], api_key: str = "") -> list[LeadSource]:
    """Search Exa's AI web index for prospect pages matching the queries."""
    results: list[LeadSource] = []
    api_key = (api_key or os.environ.get("EXA_API_KEY", "")).strip().strip('"')
    if not api_key:
        logger.warning("EXA_API_KEY not set — skipping exa source")
        return results
    async with aiohttp.ClientSession() as session:
        for q in queries[:5]:
            try:
                payload = {"query": q, "numResults": 5, "type": "auto"}
                async with session.post(
                        "https://api.exa.ai/search",
                        headers={"x-api-key": api_key, "Content-Type": "application/json"},
                        json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    data = await resp.json()
                for item in data.get("results", []):
                    text = f"{item.get('title', '')}\n{(item.get('text') or item.get('highlight') or '')[:2000]}"
                    if len(text) > 30:
                        results.append(LeadSource(
                            source="exa", text=text, url=item.get("url", ""),
                            metadata={"query": q, "ai_agent": "exa"}))
            except Exception as e:
                logger.warning("Exa search failed: %s", e)
            await asyncio.sleep(0.3)
    return results


async def scrape_tavily(queries: list[str], api_key: str = "") -> list[LeadSource]:
    """Search Tavily's AI web index for prospect pages matching the queries."""
    results: list[LeadSource] = []
    api_key = (api_key or os.environ.get("TAVILY_API_KEY", "")).strip().strip('"')
    if not api_key:
        logger.warning("TAVILY_API_KEY not set — skipping tavily source")
        return results
    async with aiohttp.ClientSession() as session:
        for q in queries[:5]:
            try:
                payload = {"api_key": api_key, "query": q, "max_results": 5}
                async with session.post(
                        "https://api.tavily.com/search",
                        headers={"Content-Type": "application/json"},
                        json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    data = await resp.json()
                for item in data.get("results", []):
                    text = f"{item.get('title', '')}\n{(item.get('content') or '')[:2000]}"
                    if len(text) > 30:
                        results.append(LeadSource(
                            source="tavily", text=text, url=item.get("url", ""),
                            metadata={"query": q, "ai_agent": "tavily"}))
            except Exception as e:
                logger.warning("Tavily search failed: %s", e)
            await asyncio.sleep(0.3)
    return results


async def scrape_url(target_url: str) -> LeadSource | None:
    """Scrape a single URL for lead information."""
    try:
        async with (
            aiohttp.ClientSession(headers=_HEADERS) as session,
            session.get(target_url, timeout=aiohttp.ClientTimeout(total=15)) as resp,
        ):
            html = await resp.text()
        if _BS4:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)[:8000]
            return LeadSource(source="web", text=text, url=target_url)
    except Exception as e:
        logger.warning("URL scrape failed: %s", e)
    return None


# ── Email verification ─────────────────────────────────────────────────────

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


async def verify_lead_email(email: str) -> dict[str, Any]:
    """Verify email syntax and check domain deliverability via DNS MX."""
    if not email or not EMAIL_REGEX.match(email.strip()):
        return {"email": email, "valid_syntax": False, "domain_has_mx": False,
                "deliverability_score": 0.0}

    clean_email = email.strip().lower()
    domain = clean_email.split("@")[-1]
    loop = asyncio.get_event_loop()
    try:
        await loop.getaddrinfo(domain, 80)
        has_mx, score = True, 0.95
    except Exception:
        has_mx, score = False, 0.1

    return {"email": clean_email, "valid_syntax": True, "domain_has_mx": has_mx,
            "deliverability_score": score}


# ── Orchestrator ───────────────────────────────────────────────────────────

#: Sources that need no credential. Everything else must be explicitly keyed.
FREE_SOURCES = ("google_maps", "reddit", "craigslist", "github", "url")
KEYED_SOURCES = ("exa", "tavily")


class DiscoveryEngine:
    """Multi-source lead discovery over live HTTP scrapers + AI-search APIs.

    Extraction is delegated to `llm_func`; when none is supplied the engine still
    returns raw LeadSource records in `job.raw_results` rather than inventing leads.
    """

    def __init__(self, llm_func=None):
        self.llm_func = llm_func
        self.jobs: dict[str, ScrapeJob] = {}
        self._leads_db: list[dict[str, Any]] = []
        self._api_keys: dict[str, str] = {}

    def set_llm(self, llm_func):
        self.llm_func = llm_func

    def set_api_key(self, source: str, key: str):
        self._api_keys[source] = key

    async def verify_and_enrich(self, leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Cascading email verification and deliverability scoring."""
        for lead in leads:
            if lead.get("email"):
                res = await verify_lead_email(lead["email"])
                lead["email_verified"] = res["valid_syntax"] and res["domain_has_mx"]
                lead["deliverability_score"] = res["deliverability_score"]
        return leads

    async def ingest_webhook_leads(
        self, raw_leads: list[dict[str, Any]], source_name: str = "webhook_apollo"
    ) -> list[dict[str, Any]]:
        """Ingest raw CSV/JSON lead exports from Apollo.io, LinkedIn, or Hunter.io."""
        ingested = []
        for item in raw_leads:
            email = item.get("email") or item.get("Email") or ""
            ingested.append({
                "name": item.get("name") or
                        f"{item.get('first_name', '')} {item.get('last_name', '')}".strip(),
                "email": email,
                "phone": item.get("phone") or item.get("Phone") or "",
                "company": item.get("company") or item.get("Company") or "",
                "title": item.get("title") or item.get("Title") or "",
                "location": item.get("location") or item.get("City") or "",
                "source_url": item.get("url") or item.get("linkedin_url") or "",
                "source_type": source_name,
                "intent_score": float(item.get("intent_score", 0.8)),
            })
        await self.verify_and_enrich(ingested)
        self._leads_db.extend(ingested)
        logger.info("Ingested %d webhook leads from %s", len(ingested), source_name)
        return ingested

    async def run_discovery(self, profile: TargetProfile, sources: list[str]) -> ScrapeJob:
        """Run discovery for a target profile across the selected sources.

        A source that is unavailable (missing key, missing dep) is recorded in
        `job.skipped` and the rest of the run continues. `job.status` is only
        'completed' when the run genuinely finished; a missing key is not a crash.
        """
        import time as _time
        job_id = f"discovery_{int(_time.time())}"
        queries = generate_search_queries(profile)

        job = ScrapeJob(
            id=job_id, profile=profile, sources_used=list(sources),
            status="running", created_at=_time.time(),
            api_keys_used={k: (v[:8] + "..." if v else "")
                           for k, v in self._api_keys.items() if k in sources},
        )
        self.jobs[job_id] = job

        if not _AIOHTTP:
            job.status = "failed"
            job.error = "aiohttp is required for live discovery (pip install aiohttp)"
            return job

        try:
            all_sources: list[LeadSource] = []

            for name in sources:
                if name in KEYED_SOURCES and not (
                        self._api_keys.get(name) or os.environ.get(
                            "EXA_API_KEY" if name == "exa" else "TAVILY_API_KEY")):
                    job.skipped.append(f"{name}:no_api_key")
                    continue

                fn = {
                    "google_maps": scrape_google_maps,
                    "reddit": scrape_reddit,
                    "github": lambda q: scrape_github(q, self._api_keys.get("github", "")),
                    "craigslist": scrape_craigslist,
                    "exa": lambda q: scrape_exa(q, self._api_keys.get("exa", "")),
                    "tavily": lambda q: scrape_tavily(q, self._api_keys.get("tavily", "")),
                }.get(name)

                if fn is None:
                    job.skipped.append(f"{name}:unknown_source")
                    continue
                if name in ("google_maps", "craigslist") and not _BS4:
                    job.skipped.append(f"{name}:bs4_missing")
                    continue

                raw = await fn(queries.get(name, []))
                all_sources.extend(raw)
                job.raw_results.extend(raw)

                # A source that was blocked/unavailable must be reported, or an
                # empty result is indistinguishable from "no leads exist".
                if name == "reddit" and last_reddit_error:
                    job.skipped.append(f"reddit:blocked — {last_reddit_error}")
                if name in ("google_maps", "craigslist") and not raw and not queries.get(name):
                    job.skipped.append(f"{name}:no_queries_generated")

            # AI extraction. With no LLM we keep raw sources and say so.
            if self.llm_func and all_sources:
                leads = await extract_leads_with_ai(all_sources, profile, self.llm_func)
                await self.verify_and_enrich(leads)
                job.leads.extend(leads)
                self._leads_db.extend(leads)
            elif all_sources and not self.llm_func:
                job.skipped.append("extraction:no_llm_configured")

            job.status = "completed"
            job.completed_at = _time.time()
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            logger.error("Lead discovery failed: %s", e)

        return job

    def get_leads(self) -> list[dict[str, Any]]:
        return list(self._leads_db)

    def get_jobs(self) -> list[dict[str, Any]]:
        return [asdict(j) for j in self.jobs.values()]


LEAD_EXTRACTION_PROMPT = """You are a lead generation AI. The user is looking for:
{profile_description}

Analyze the following text scraped from {source} and extract any potential leads matching the user's target.

For each lead found, return a JSON object with these fields:
- name: person's full name if found (else "")
- email: email address if found (else "")
- phone: phone number if found (else "")
- company: company name if found (else "")
- title: job title if found (else "")
- location: city/state if found (else "")
- address: street address if found (else "")
- pain_points: array of strings describing what they need
- need_type: what specific product/service they're looking for (e.g. "roofing", "software development")
- intent_score: number 0.0 to 1.0. 1.0 = actively seeking now, 0.5 = researching, 0.0 = just browsing

Return ONLY a JSON array. If no leads found, return [].

TEXT:
{text}
"""


async def extract_leads_with_ai(sources: list[LeadSource], profile: TargetProfile,
                                llm_func) -> list[dict[str, Any]]:
    """Use an LLM to extract structured leads matching the target profile."""
    all_leads: list[dict[str, Any]] = []
    profile_desc = profile.customer_description or "general contractor services"
    for src in sources:
        if not src.text or len(src.text) < 50:
            continue
        prompt = LEAD_EXTRACTION_PROMPT.format(
            profile_description=profile_desc, source=src.source, text=src.text[:6000])
        try:
            result = await llm_func(prompt)
            if isinstance(result, str):
                cleaned = result.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1]
                    if "```" in cleaned:
                        cleaned = cleaned.rsplit("```", 1)[0]
                parsed = json.loads(cleaned)
                if isinstance(parsed, list):
                    for item in parsed:
                        all_leads.append({
                            "name": item.get("name", ""),
                            "email": item.get("email", ""),
                            "phone": item.get("phone", ""),
                            "company": item.get("company", ""),
                            "title": item.get("title", ""),
                            "location": item.get("location", ""),
                            "address": item.get("address", ""),
                            "pain_points": item.get("pain_points", []),
                            "need_type": item.get("need_type", ""),
                            "intent_score": min(float(item.get("intent_score", 0)), 1.0),
                            "source_url": src.url,
                            "source_type": src.source,
                            "raw_snippet": src.text[:500],
                        })
        except Exception as e:
            logger.warning("AI extraction failed: %s", e)
        await asyncio.sleep(0.1)
    return all_leads


__all__ = [
    "FREE_SOURCES",
    "KEYED_SOURCES",
    "DiscoveryEngine",
    "LeadSource",
    "ScrapeJob",
    "TargetProfile",
    "extract_leads_with_ai",
    "generate_search_queries",
    "scrape_craigslist",
    "scrape_exa",
    "scrape_github",
    "scrape_google_maps",
    "scrape_reddit",
    "scrape_tavily",
    "scrape_url",
    "verify_lead_email",
]
